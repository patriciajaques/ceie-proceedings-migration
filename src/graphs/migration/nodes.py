from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.types import Send

from src.domain.article import Article
from src.domain.reference import Reference
from src.io.csv_writer import CsvWriter
from src.logging.json_logger import JsonLogger

from .state import MigrationState


def _stage(title: str) -> None:
    """User-visible pipeline step (Portuguese)."""
    print(f"\n>>> {title}", flush=True)


def _article_id_jems_from_dict(ad: dict[str, Any]) -> str:
    return str(ad.get("idJEMS") or ad.get("id_jems") or "").strip()


def _references_cache_path(state: MigrationState) -> Path:
    return Path(state.logs_dir) / "references_cache.json"


def _load_references_cache(state: MigrationState) -> dict[str, list[dict[str, Any]]]:
    path = _references_cache_path(state)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _save_references_cache(
    state: MigrationState, cache: dict[str, list[dict[str, Any]]]
) -> None:
    path = _references_cache_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def node_fetch_website_articles(state: MigrationState, migrator) -> MigrationState:
    _stage("Artigos: obter metadados do site (ou carregar cache)")
    website_articles_data_list = migrator._get_website_articles_data(
        state.files_to_download,
        state.article_offset,
    )
    state.website_articles_data_list = website_articles_data_list or []
    n = len(state.website_articles_data_list)
    off = state.article_offset
    if n > 0:
        print(
            f"Lote: artigos {off + 1}–{off + n} da edição "
            f"(article_offset={off}, files_to_download={state.files_to_download}).",
            flush=True,
        )
    elif off > 0:
        print(
            f"Aviso: nenhum artigo no intervalo "
            f"(offset={off}); verifique article_offset e files_to_download.",
            flush=True,
        )
    return state


def node_validate_year(state: MigrationState, migrator) -> MigrationState:
    _stage("Validação: conferir se o ano da configuração coincide com o site")
    migrator._validate_year_matches_site_or_abort(state.website_articles_data_list)
    return state


def node_download_pdfs(state: MigrationState, migrator) -> MigrationState:
    _stage("PDFs: descarregar ficheiros em falta (lote atual)")
    migrator.downloader.donwload_pdf_files_from_url(
        state.files_to_download,
        start_index=state.article_offset,
    )
    return state


def node_infer_doi_prefix(state: MigrationState, migrator) -> MigrationState:
    _stage("DOI: inferir prefixo a partir dos metadados do site (se houver DOIs)")
    extracted_dois: list[str] = []
    for website_article in state.website_articles_data_list or []:
        if isinstance(website_article, dict) and website_article.get("doi"):
            extracted_dois.append(website_article["doi"])
    if extracted_dois:
        state.inferred_doi_prefix = migrator._infer_doi_prefix(extracted_dois)
        migrator.inferred_doi_prefix = state.inferred_doi_prefix
    return state


def node_extract_sections_and_write_csv(state: MigrationState, migrator) -> MigrationState:
    _stage("Secções: extrair do site e gravar Secoes.csv")
    sections_data = migrator.parser.extract_sections_from_website()
    state.sections_data = sections_data or []
    CsvWriter.write_sections_csv(state.csv_save_dir, state.sections_data)
    return state


def node_build_articles_from_site(state: MigrationState) -> MigrationState:
    _stage("Modelo: converter metadados do site em artigos (Article)")
    articles_list: list[Article] = []
    for website_article in state.website_articles_data_list or []:
        if not isinstance(website_article, dict):
            continue
        articles_list.append(Article.from_dict(website_article))
    state.articles_dict_list = [a.to_dict() for a in articles_list]
    print(f"    {len(articles_list)} artigo(s) no lote.", flush=True)
    return state


def node_skip_completed_articles(state: MigrationState, migrator) -> MigrationState:
    """
    Remove articles already fully saved in articles_metadata_apos from the enrich
    pipeline; they are merged back in enrich_merge via skipped_enrichment_chunks.
    """
    s = MigrationState.model_validate(state)
    if s.skip_fully_processed_articles:
        _stage("Filtro: verificar artigos já completos (field completion anterior)")
    if not s.skip_fully_processed_articles:
        print(
            "    (skip_fully_processed_articles desligado — todos seguem para "
            "enriquecimento.)",
            flush=True,
        )
        return s.model_copy(
            update={
                "skipped_enrichment_chunks": [],
                "enrichment_global_orders": None,
            }
        )

    cache = migrator._load_completion_cache()
    extractor = migrator.extractor
    full_list = [d for d in (s.articles_dict_list or []) if isinstance(d, dict)]
    pending: list[dict[str, Any]] = []
    orders: list[int] = []
    skipped: list[dict[str, Any]] = []

    for global_idx, ad in enumerate(full_list):
        aid = _article_id_jems_from_dict(ad)
        cached = cache.get(aid) if aid else None
        if (
            aid
            and cached is not None
            and not extractor.has_empty_fields(cached)
        ):
            skipped.append(
                {
                    "order": global_idx,
                    "id_jems": aid,
                    "article_dict": dict(cached),
                }
            )
        else:
            pending.append(ad)
            orders.append(global_idx)

    if skipped:
        print(
            f"    Pulando enriquecimento (PDF/refs) para {len(skipped)} artigo(s) "
            f"já completos em articles_metadata_apos_do_field_completion.json.",
            flush=True,
        )
    print(
        f"    Pendentes de enriquecimento neste lote: {len(pending)} artigo(s).",
        flush=True,
    )

    return s.model_copy(
        update={
            "articles_dict_list": pending,
            "skipped_enrichment_chunks": skipped,
            "enrichment_global_orders": orders if pending else None,
        }
    )


def route_after_skip_articles(state: MigrationState | dict) -> str:
    """If no pending articles, skip enrich_prepare and PDF loading."""
    s = MigrationState.model_validate(state)
    if s.articles_dict_list:
        return "enrich_prepare"
    return "enrich_merge"


def node_enrich_prepare(state: MigrationState, migrator) -> MigrationState:
    """
    Load all PDFs once and attach lookup tables on the migrator for per-article workers.
    """
    s = MigrationState.model_validate(state)
    n_pending = len(s.articles_dict_list or [])
    _stage(
        "Enriquecimento: extrair texto dos PDFs (pode demorar) e preparar cache "
        f"de referências — {n_pending} artigo(s) em paralelo a seguir"
    )
    all_files_data = migrator.processor.process_all_pdfs(
        save_files=False, number_of_pages_to_process=s.pages_to_process
    )
    pdf_by_id = {
        (item.get("base_filename") or "").strip(): item
        for item in (all_files_data or [])
        if isinstance(item, dict) and (item.get("base_filename") or "").strip()
    }
    migrator._enrich_pdf_by_id = pdf_by_id
    migrator._enrich_pdf_files_data = all_files_data
    migrator._refs_cache = _load_references_cache(s)
    n_pdf = len(pdf_by_id)
    print(
        f"    PDFs indexados para enriquecimento: {n_pdf} ficheiro(s).",
        flush=True,
    )
    return s


def route_enrich_articles(state: MigrationState | dict) -> list[Send] | str:
    s = MigrationState.model_validate(state)
    articles = s.articles_dict_list or []
    if not articles:
        return "enrich_merge"
    # Send() replaces the worker input; merge full state so nodes can validate
    # MigrationState (LangGraph does not auto-merge parent state into Send payloads).
    base = s.model_dump()
    global_orders = s.enrichment_global_orders
    return [
        Send(
            "enrich_one_article",
            {
                **base,
                "enrichment_order": (
                    global_orders[i]
                    if global_orders is not None and i < len(global_orders)
                    else i
                ),
                "enrichment_article_dict": ad,
            },
        )
        for i, ad in enumerate(articles)
    ]


def node_enrich_one_article(
    state: MigrationState, migrator
) -> dict[str, Any]:
    """
    Enrich a single article from PDF data (pages, references, DOI). Results are merged
    in enrich_merge via enriched_article_chunks reducer.
    """
    s = MigrationState.model_validate(state)
    order = s.enrichment_order
    article_dict = s.enrichment_article_dict or {}
    article = Article.from_dict(article_dict)
    id_jems = getattr(article, "id_jems", "") or ""
    print(
        f"    [enriquecimento] Artigo idJEMS={id_jems} (ordem na edição: {order})…",
        flush=True,
    )
    pdf_by_id = getattr(migrator, "_enrich_pdf_by_id", {}) or {}
    pdf_item = pdf_by_id.get(str(id_jems).strip())
    refs_cache = getattr(migrator, "_refs_cache", {}) or {}

    chunk: dict[str, Any] = {
        "order": order,
        "id_jems": str(id_jems).strip(),
    }

    if pdf_item:
        num_pages_pdf = pdf_item.get("numPages", 0) or 0
        try:
            article.num_pages = int(num_pages_pdf)
        except Exception:
            article.num_pages = 0
        article.pages = migrator.update_pages(article.first_page, article.num_pages)

        if getattr(article, "section_abbrev", "") != "EDT":
            cache_key = str(id_jems).strip()
            cached_refs = refs_cache.get(cache_key)
            if cached_refs is None:
                refs = migrator._extract_references_from_pdf_item(pdf_item)
                chunk["refs_cache_key"] = cache_key
                chunk["refs_cache_entry"] = refs
            else:
                refs = cached_refs

            article.references = [
                Reference.from_dict(r)
                if isinstance(r, dict)
                else Reference(description=str(r), order=i)
                for i, r in enumerate(refs, start=1)
            ]
        else:
            article.references = []

    migrator.correct_doi(article)
    chunk["article_dict"] = article.to_dict()

    print(
        f"    [enriquecimento] Concluído idJEMS={id_jems}.",
        flush=True,
    )
    # Return only the reducer field — parallel workers must not write site_url etc.
    return {"enriched_article_chunks": [chunk]}


def node_enrich_merge(state: MigrationState, migrator) -> MigrationState:
    """
    Order enriched articles, persist references cache, log, and keep PDF data for field
    completion.
    """
    s = MigrationState.model_validate(state)
    _stage("Enriquecimento: juntar artigos, gravar cache de referências e JSON intermédio")
    worker_chunks = sorted(s.enriched_article_chunks or [], key=lambda x: x["order"])
    skipped_chunks = list(s.skipped_enrichment_chunks or [])
    chunks = sorted(
        worker_chunks + skipped_chunks,
        key=lambda x: x["order"],
    )
    refs_cache = _load_references_cache(s)
    for ch in chunks:
        key = ch.get("refs_cache_key")
        if key is not None and "refs_cache_entry" in ch:
            refs_cache[key] = ch["refs_cache_entry"]
    _save_references_cache(s, refs_cache)
    migrator._refs_cache = refs_cache

    articles_dict_list = [c["article_dict"] for c in chunks]
    JsonLogger.print_json("articles_metadata_antes_do_field_completion", articles_dict_list)

    migrator._last_pdf_files_data = getattr(migrator, "_enrich_pdf_files_data", None)

    print(
        f"    Gravado articles_metadata_antes_do_field_completion.json "
        f"({len(articles_dict_list)} artigo(s)).",
        flush=True,
    )

    return MigrationState.model_validate(state).model_copy(
        update={
            "articles_dict_list": articles_dict_list,
            "skipped_enrichment_chunks": [],
            "enrichment_global_orders": None,
        }
    )


def node_field_prepare(state: MigrationState, migrator) -> MigrationState:
    """
    Load completion cache and PDF raw snippets for field-completion workers.
    Mirrors the legacy JSON load when the article list is empty (tests).
    """
    s = MigrationState.model_validate(state)
    _stage("Field completion: carregar cache anterior e excertos das primeiras páginas dos PDFs")
    articles = list(s.articles_dict_list or [])
    if not articles:
        try:
            loaded = JsonLogger.read_json_file(
                "articles_metadata_antes_do_field_completion.json"
            )
            if isinstance(loaded, list):
                articles = loaded
            elif isinstance(loaded, dict) and "data" in loaded:
                data = loaded["data"]
                if isinstance(data, list):
                    articles = data
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            pass

    migrator._field_completion_cache = migrator._load_completion_cache()
    migrator._field_completion_pdf_raw_by_id = migrator._build_pdf_raw_by_id()

    print(
        f"    {len(articles)} artigo(s) para completar campos com IA (em paralelo).",
        flush=True,
    )

    return MigrationState.model_validate(state).model_copy(
        update={"articles_dict_list": articles}
    )


def route_field_completion(state: MigrationState | dict) -> list[Send] | str:
    s = MigrationState.model_validate(state)
    articles = s.articles_dict_list or []
    if not articles:
        return "field_merge"
    base = s.model_dump()
    return [
        Send(
            "field_one_article",
            {
                **base,
                "field_completion_order": i,
                "field_completion_article_dict": ad,
            },
        )
        for i, ad in enumerate(articles)
    ]


def node_field_one_article(state: MigrationState, migrator) -> dict[str, Any]:
    s = MigrationState.model_validate(state)
    order = s.field_completion_order
    article_dict = s.field_completion_article_dict or {}
    article = Article.from_dict(article_dict)
    aid = _article_id_jems_from_dict(article_dict)
    print(
        f"    [field completion] Artigo idJEMS={aid or '?'} (#{order + 1})…",
        flush=True,
    )

    completion_cache = getattr(migrator, "_field_completion_cache", {}) or {}
    pdf_raw_by_id = getattr(migrator, "_field_completion_pdf_raw_by_id", {}) or {}

    updated = migrator.extractor.do_field_completion_of_missing_values_in_dic(
        [article],
        completion_cache=completion_cache,
        pdf_raw_by_id=pdf_raw_by_id,
    )
    out = updated[0] if updated else article
    chunk = {"order": order, "article_dict": out.to_dict()}

    print(
        f"    [field completion] Concluído idJEMS={aid or '?'}.",
        flush=True,
    )
    # Return only the reducer field — parallel workers must not write site_url etc.
    return {"field_completion_chunks": [chunk]}


def node_field_merge(state: MigrationState, migrator) -> MigrationState:
    s = MigrationState.model_validate(state)
    _stage("Field completion: juntar resultados, gravar JSON final e CSVs (Artigos, Autores, Referências)")
    chunks = sorted(s.field_completion_chunks or [], key=lambda x: x["order"])
    updated_articles = [Article.from_dict(c["article_dict"]) for c in chunks]
    merged_articles = migrator.finalize_field_completion_outputs(updated_articles)
    return MigrationState.model_validate(state).model_copy(
        update={
            "updated_articles_dict_list": [a.to_dict() for a in merged_articles],
        }
    )
