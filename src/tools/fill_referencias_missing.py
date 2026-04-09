"""
Tool: detect articles with no references in Referencias.csv and generate them.

Analyzes output/{year}/csv/Referencias.csv and Artigos.csv; for each article (seq)
that has no rows in Referencias, extracts references from the article PDF (last pages)
using the same pipeline as the main migration (PDFProcessor + ArticleExtractor
extract_references_metadata_with_ai). Appends new rows to Referencias.csv after
creating a backup.

Run from project root:
  python -m src.tools.fill_referencias_missing

Configure dry_run, max_articles and year as variables in main().
"""
import csv
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

# Project root (parent of src)
ROOT = Path(__file__).resolve().parents[2]


def _sanitize_cell(value: str) -> str:
    """Replace newlines and normalize spaces for CSV cell (match CsvWriter)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


def _load_config_and_deps():
    """Load config and build ArticleExtractor + PDFProcessor (same as main)."""
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=ROOT / ".env")

    from src.config.config_loader import ConfigLoader
    from src.adapters.langchain_client import LangChainClient
    from src.services.article_extractor import ArticleExtractor
    from src.utils.text_processor import TextProcessor

    config_loader = ConfigLoader(str(ROOT / "config" / "config.json"))
    client_specs = {
        "article_ai_client": "article_extraction",
        "references_ai_client": "references_extraction",
        "field_completion_ai_client": "field_completion",
        "text_processing_client": "text_processing",
    }
    ai_clients = {
        key: LangChainClient(config_loader, prompt_key)
        for key, prompt_key in client_specs.items()
    }
    text_processor = TextProcessor(ai_clients["text_processing_client"])
    article_extractor = ArticleExtractor(
        ai_clients["article_ai_client"],
        ai_clients["references_ai_client"],
        ai_clients["field_completion_ai_client"],
        text_processor,
    )
    return config_loader, article_extractor, text_processor


def _articles_without_references(
    artigos_df: pd.DataFrame, refs_df: pd.DataFrame
) -> pd.DataFrame:
    """Return Artigos rows for articles that have no entries in Referencias."""
    refs_df = refs_df.copy()
    refs_df["article"] = refs_df["article"].astype(str).str.strip()
    articles_with_refs = set(refs_df["article"].unique())

    artigos_df = artigos_df.copy()
    artigos_df["seq"] = artigos_df["seq"].astype(str).str.strip()
    # Exclude editorials (no references expected) and articles that already have refs
    mask = (
        (artigos_df["sectionAbbrev"].astype(str).str.strip() != "EDT")
        & (~artigos_df["seq"].isin(articles_with_refs))
    )
    return artigos_df[mask].copy()


def _build_one_article_text(pdf_path: str, pdf_processor) -> dict:
    """Build one_article_text dict for reference page extraction."""
    text_pages, num_pages = pdf_processor.extract_text_from_each_page(
        pdf_path
    )
    return {
        "text_pages": text_pages,
        "numPages": num_pages,
        "base_filename": Path(pdf_path).stem,
    }


def _extract_reference_pages_text(
    pdf_path: str, pdf_processor, text_processor, extractor, strategy: str
) -> str:
    """Get cleaned text for reference extraction (last 2 pages or section)."""
    one_article_text = _build_one_article_text(pdf_path, pdf_processor)
    raw = extractor.get_reference_pages_text(one_article_text, strategy=strategy)
    return text_processor.clean_text(raw)


def run(
    dry_run: bool = False,
    max_articles: int | None = None,
    year: str | None = None,
) -> None:
    """Find articles without references, extract from PDFs, append to Referencias.csv."""
    config_loader, article_extractor, text_processor = _load_config_and_deps()
    year = year or str(config_loader.get_config_value("year", "2018"))
    output_dir = Path(config_loader.get_config_value("output_dir", "output/"))
    csv_dir = output_dir / year / "csv"
    pdfs_dir = output_dir / year / "pdfs"
    artigos_path = csv_dir / "Artigos.csv"
    refs_path = csv_dir / "Referencias.csv"

    if not artigos_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {artigos_path}")
    if not refs_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {refs_path}")

    artigos_df = pd.read_csv(artigos_path, delimiter=";")
    refs_df = pd.read_csv(refs_path, delimiter=";")

    to_process = _articles_without_references(artigos_df, refs_df)
    # Only articles that have a PDF
    to_process = to_process.copy()
    to_process["idJEMS"] = to_process["idJEMS"].astype(str).str.strip()
    to_process["_pdf_path"] = to_process["idJEMS"].apply(
        lambda x: pdfs_dir / f"{x}.pdf"
    )
    to_process = to_process[to_process["_pdf_path"].apply(lambda p: p.exists())].copy()

    if max_articles is not None and max_articles > 0:
        to_process = to_process.head(max_articles)

    if to_process.empty:
        print("Nenhum artigo sem referências (com PDF) encontrado.")
        return

    print(f"Artigos sem referências (com PDF disponível): {len(to_process)}")
    print("Seq(s):", ", ".join(to_process["seq"].astype(str).tolist()))

    if dry_run:
        print("[DRY-RUN] Nenhuma alteração em disco.")
        return

    from src.utils.pdf_processor import PDFProcessor

    pdf_processor = PDFProcessor(str(pdfs_dir))
    headers_refs = ["article", "description", "doi", "link", "accessed", "order"]
    new_rows: list[dict] = []

    for idx, row in to_process.iterrows():
        seq = str(row["seq"]).strip()
        id_jems = str(row["idJEMS"]).strip()
        pdf_path = row["_pdf_path"]
        print(f"Extraindo referências: seq={seq}, idJEMS={id_jems} ...", flush=True)
        try:
            # Prefer section: if we find "Referências"/"References" (from end backward), use that block
            section_text = _extract_reference_pages_text(
                str(pdf_path),
                pdf_processor,
                text_processor,
                article_extractor,
                strategy="section",
            )
            if section_text:
                refs_dict = article_extractor.extract_references_metadata_with_ai(
                    section_text
                )
                refs_list = refs_dict.get("references") or []
            else:
                refs_list = []
            # Fallback: if section not found or gave few refs, try last 3 pages
            if len(refs_list) < 2:
                last_pages_text = _extract_reference_pages_text(
                    str(pdf_path),
                    pdf_processor,
                    text_processor,
                    article_extractor,
                    strategy="last",
                )
                refs_dict = article_extractor.extract_references_metadata_with_ai(
                    last_pages_text
                )
                last_refs = refs_dict.get("references") or []
                if len(last_refs) > len(refs_list):
                    refs_list = last_refs
        except Exception as e:
            print(f"  Erro ao extrair referências para seq={seq}: {e}", flush=True)
            continue

        for order, ref in enumerate(refs_list, start=1):
            if isinstance(ref, dict):
                new_rows.append({
                    "article": seq,
                    "description": _sanitize_cell(ref.get("description", "")),
                    "doi": _sanitize_cell(ref.get("doi", "")),
                    "link": _sanitize_cell(ref.get("link", "")),
                    "accessed": _sanitize_cell(ref.get("accessed", "")),
                    "order": order,
                })
            else:
                new_rows.append({
                    "article": seq,
                    "description": _sanitize_cell(str(ref)),
                    "doi": "",
                    "link": "",
                    "accessed": "",
                    "order": order,
                })
        print(f"  -> {len(refs_list)} referência(s) extraída(s).", flush=True)

    if not new_rows:
        print("Nenhuma referência nova gerada. Referencias.csv não foi alterado.")
        return

    # Backup
    backup_dir = csv_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"Referencias_backup_{timestamp}.csv"
    refs_df.to_csv(backup_path, sep=";", index=False, quoting=csv.QUOTE_ALL)
    print(f"Backup salvo em: {backup_path}")

    # Append new rows, sort by article id (numeric) then by order, and save
    new_df = pd.DataFrame(new_rows, columns=headers_refs)
    combined = pd.concat([refs_df, new_df], ignore_index=True)
    combined["_article_num"] = pd.to_numeric(combined["article"], errors="coerce").fillna(0)
    combined = combined.sort_values(by=["_article_num", "order"]).drop(columns=["_article_num"])
    combined.to_csv(refs_path, sep=";", index=False, quoting=csv.QUOTE_ALL)
    print(f"Referencias.csv atualizado: {len(new_rows)} nova(s) linha(s) adicionada(s) (ordenado por article).")


def main() -> None:
    dry_run = False
    max_articles = None
    year = None

    run(dry_run=dry_run, max_articles=max_articles, year=year)


if __name__ == "__main__":
    main()
