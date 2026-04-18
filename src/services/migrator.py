# src/services/migrator.py
from __future__ import annotations

import json
from typing import Any

from src.config.config_loader import ConfigLoader
from src.services.pdf_downloader import PDFDownloader
from src.utils.pdf_processor import PDFProcessor
from src.services.anais_ojs_html_parser import OJSHTMLParser
from src.services.article_extractor import ArticleExtractor
from src.io.csv_writer import CsvWriter
from src.logging.json_logger import JsonLogger
from src.domain.article import Article
from src.domain.reference import Reference
import os
import re
import threading


def _article_id_from_dict(d: dict[str, Any]) -> str:
    """Stable id for merge keys (website uses idJEMS)."""
    return str(d.get("idJEMS") or d.get("id_jems") or "").strip()


class Migrator:
    """
    Services used by the LangGraph migration pipeline (nodes in src/graphs/migration/).

    Website (Milanesa/OJS) is the primary source for titles, authors, abstracts, and DOIs.
    PDF text is used for page counts and reference extraction; field completion fills gaps.
    """

    def __init__(
        self, config_loader: ConfigLoader, article_extractor: ArticleExtractor
    ):
        """
        Initializes the Migrator with the necessary components.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            article_extractor (ArticleExtractor): Article extractor instance.
        """
        self.config_loader = config_loader
        # Load configuration values
        self.site_url = config_loader.get_config_value("site_url")
        self.output_dir = config_loader.get_config_value("output_dir")
        self.year = config_loader.get_config_value("year")
        # doi_prefix is now optional - will be inferred from extracted DOIs if not provided
        self.doi_prefix = config_loader.get_config_value("doi_prefix", None)
        self.inferred_doi_prefix = None  # Will be set after extracting DOIs

        # Generate directories based on year
        self.pdf_save_dir = os.path.join(self.output_dir, f"{self.year}", "pdfs")
        self.csv_save_dir = os.path.join(self.output_dir, f"{self.year}", "csv")

        # Ensure directories exist
        os.makedirs(self.pdf_save_dir, exist_ok=True)
        os.makedirs(self.csv_save_dir, exist_ok=True)

        self.downloader = PDFDownloader(self.site_url, self.pdf_save_dir)
        self.processor = PDFProcessor(self.pdf_save_dir)
        self.parser = OJSHTMLParser(self.site_url)
        self.extractor = article_extractor

        # Populated during enrich_one_article; reused in _build_pdf_raw_by_id for the
        # same batch (at most one pdf_item per article in the lot, not all 150 PDFs).
        self._pdf_item_cache: dict[str, dict[str, Any]] = {}
        self._pdf_item_cache_lock = threading.Lock()

    def _extract_references_from_pdf_item(self, pdf_item: dict) -> list[dict]:
        """
        Extract references from a processed PDF item dict (from PDFProcessor).

        Uses the same strategy as other tooling:
        - Prefer "section" (detect heading Referências/References)
        - Fallback to "last" pages if section yields too few items
        """
        try:
            section_text_raw = self.extractor.get_reference_pages_text(
                pdf_item, strategy="section"
            )
            section_text = self.extractor.text_processor.clean_text(section_text_raw)
        except Exception:
            section_text = ""

        refs_list: list[dict] = []
        if section_text:
            try:
                refs_dict = self.extractor.extract_references_metadata_with_ai(
                    section_text
                )
                refs_list = refs_dict.get("references") or []
            except Exception:
                refs_list = []

        if len(refs_list) < 2:
            try:
                last_text_raw = self.extractor.get_reference_pages_text(
                    pdf_item, strategy="last"
                )
                last_text = self.extractor.text_processor.clean_text(last_text_raw)
                refs_dict = self.extractor.extract_references_metadata_with_ai(last_text)
                last_refs = refs_dict.get("references") or []
                if len(last_refs) > len(refs_list):
                    refs_list = last_refs
            except Exception:
                pass

        # Normalize to list[dict] only
        normalized: list[dict] = []
        for i, ref in enumerate(refs_list, start=1):
            if isinstance(ref, dict):
                ref_copy = dict(ref)
                ref_copy.setdefault("order", i)
                normalized.append(ref_copy)
            elif ref:
                normalized.append({"description": str(ref), "order": i})
        return normalized

    @staticmethod
    def _infer_year_from_dois(dois: list[str]) -> str | None:
        """
        Infer the most likely year from a list of DOI strings.

        Strategy: extract all 4-digit years (19xx or 20xx), then return the
        most frequent one. Returns None if no year can be inferred.
        """
        if not dois:
            return None

        years: list[str] = []
        for doi in dois:
            if not doi:
                continue
            matches = re.findall(r"\b(19\d{2}|20\d{2})\b", str(doi))
            years.extend(matches)

        if not years:
            return None

        from collections import Counter

        return Counter(years).most_common(1)[0][0]

    def _validate_year_matches_site_or_abort(self, website_articles_data_list) -> None:
        """
        Abort the migration if the configured year does not match the website year.

        The website year is inferred from article DOIs extracted from the Milanesa
        metadata pages. If no DOIs or no year can be inferred, validation is skipped.
        """
        try:
            config_year = str(self.year).strip()
        except Exception:
            config_year = ""

        dois: list[str] = []
        for item in website_articles_data_list or []:
            doi = (item.get("doi") or "").strip() if isinstance(item, dict) else ""
            if doi:
                dois.append(doi)

        inferred_year = self._infer_year_from_dois(dois)
        if not inferred_year:
            # No reliable signal to validate; do not block the run.
            return

        if config_year != inferred_year:
            raise ValueError(
                "Ano do config divergente do ano inferido a partir do Milanesa. "
                f"config.year='{config_year}' | ano_inferido='{inferred_year}'. "
                "Ajuste o campo 'year' em config/config.json ou aponte 'site_url' "
                "para o issue correto."
            )

    @staticmethod
    def _slice_article_list(
        full_list: list,
        num_files: int,
        offset: int,
    ) -> list:
        """Return full_list[offset : offset + num_files] or tail when num_files == -1."""
        if offset < 0:
            offset = 0
        if not full_list or offset >= len(full_list):
            return []
        if num_files == -1:
            return full_list[offset:]
        return full_list[offset : offset + num_files]

    def _get_website_articles_data(self, num_files: int, offset: int = 0):
        """
        Obtém metadados dos artigos do site. Usa cache em execuções subsequentes
        para evitar novas requisições HTTP ao site.

        Para forçar nova raspagem (ex.: após mudar siglas no parser), apague
        ``website_articles_cache.json`` em ``output/{year}/logs/``.

        Args:
            num_files: Quantidade de artigos a processar (-1 = todos a partir de offset).
            offset: Ignorar os primeiros N artigos (ordem da edição no cache).
        """
        cache_path = os.path.join(
            self.output_dir, str(self.year), "logs", "website_articles_cache.json"
        )
        try:
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, list) and cached:
                    print(
                        f"Metadados do site carregados do cache ({len(cached)} artigos)"
                    )
                    return self._slice_article_list(cached, num_files, offset)
        except (json.JSONDecodeError, IOError):
            pass

        # Sempre busca a lista completa para popular o cache
        website_articles_data_list = self.parser.extract_articles_info_from_the_website(
            -1
        )
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(website_articles_data_list, f, ensure_ascii=False, indent=2)
        return self._slice_article_list(website_articles_data_list, num_files, offset)

    def _logs_dir(self) -> str:
        return os.path.join(self.output_dir, str(self.year), "logs")

    def _load_articles_metadata_apos_dicts(self) -> list[dict[str, Any]]:
        """
        Load previously saved post-field-completion article dicts (any batch).
        """
        try:
            data = JsonLogger.read_json_file(
                "articles_metadata_apos_do_field_completion.json"
            )
            if isinstance(data, dict) and "data" in data:
                data = data["data"]
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and _article_id_from_dict(d)]
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError):
            pass
        return []

    def _full_issue_id_order(self) -> list[str]:
        """
        idJEMS order as in website_articles_cache.json (full issue list).
        """
        cache_path = os.path.join(self._logs_dir(), "website_articles_cache.json")
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            return []
        if not isinstance(data, list):
            return []
        ids: list[str] = []
        for item in data:
            if isinstance(item, dict):
                k = _article_id_from_dict(item)
                if k:
                    ids.append(k)
        return ids

    def _merge_articles_for_full_output(
        self,
        previous_dicts: list[dict[str, Any]],
        current_batch: list[Article],
    ) -> list[Article]:
        """
        Merge prior runs with the current batch; current batch wins on id collision.
        Order follows full issue list when available, else seq.
        """
        by_id: dict[str, dict[str, Any]] = {}
        for d in previous_dicts:
            k = _article_id_from_dict(d)
            if k:
                by_id[k] = d
        for article in current_batch:
            d = article.to_dict()
            k = _article_id_from_dict(d)
            if k:
                by_id[k] = d

        order = self._full_issue_id_order()
        merged_dicts: list[dict[str, Any]] = []
        if order:
            seen: set[str] = set()
            for oid in order:
                if oid in by_id:
                    merged_dicts.append(by_id[oid])
                    seen.add(oid)
            for k, d in sorted(by_id.items()):
                if k not in seen:
                    merged_dicts.append(d)
        else:
            merged_dicts = list(by_id.values())
            merged_dicts.sort(
                key=lambda x: (
                    int(x.get("seq") or 0),
                    _article_id_from_dict(x),
                )
            )
        return [Article.from_dict(d) for d in merged_dicts]

    def _load_completion_cache(self):
        """
        Carrega o cache de field completion de execuções anteriores.
        Retorna um dicionário {idJEMS: article_dict} para reutilizar artigos já processados.
        """
        by_list = self._load_articles_metadata_apos_dicts()
        if by_list:
            return {_article_id_from_dict(d): d for d in by_list}
        return {}

    def _build_pdf_raw_by_id(
        self,
        articles: list[dict[str, Any]],
        pages_to_process: int,
    ) -> dict[str, str]:
        """
        Build id_jems -> raw first-page text for field completion.

        Reuses ``_pdf_item_cache`` filled during enrich when possible (same batch).
        Falls back to disk for skipped-enrich articles or cache misses.
        No clean_text here; correction runs per article during field completion.
        """
        raw_by_id: dict[str, str] = {}
        for ad in articles:
            if not isinstance(ad, dict):
                continue
            aid = _article_id_from_dict(ad)
            if not aid:
                continue
            with self._pdf_item_cache_lock:
                item = self._pdf_item_cache.get(aid)
            if item is None:
                pdf_path = os.path.join(self.pdf_save_dir, f"{aid}.pdf")
                if not os.path.isfile(pdf_path):
                    continue
                try:
                    item = self.processor.process_pdf_at_path(pdf_path, pages_to_process)
                except Exception:
                    continue
            first_pages = self.extractor.extract_pages(item, "first")
            raw_by_id[aid] = first_pages
        return raw_by_id

    def enrich_article_authors_affiliation_email_with_llm(
        self,
        articles: list[Article],
        max_pages_per_pdf: int = 1,
    ) -> None:
        """
        Fill missing authorAffiliation, authorAffiliationEn, authorCountry, and
        authorEmail from PDF text via a single LLM call per article.

        Uses the first PDF page only (see AuthorsEmailExtractor). Called after
        field completion and before writing CSVs.
        """
        if not articles:
            return

        from src.adapters.langchain_client import LangChainClient
        from src.services.authors_email_extractor import AuthorsEmailExtractor

        print(
            "\n>>> Afiliações, país e e-mails: completar com IA (1ª página do PDF)",
            flush=True,
        )
        client = LangChainClient(
            self.config_loader, "author_affiliation_email_extraction"
        )
        helper = AuthorsEmailExtractor(self.config_loader)
        helper.apply_affiliation_email_llm_to_article_objects(
            articles,
            client,
            self.processor,
            max_pages_per_pdf=max_pages_per_pdf,
        )

    def finalize_field_completion_outputs(
        self, updated_articles: list[Article]
    ) -> list[Article]:
        """
        Log JSON and write CSVs after field completion.

        Merges articles from previous runs (articles_metadata_apos_do_field_completion.json)
        with the current batch so CSVs always list every article processed so far, in issue
        order (website_articles_cache.json). Current batch overwrites same idJEMS.

        Returns:
            Full merged list of Article objects (for graph state).
        """
        previous = self._load_articles_metadata_apos_dicts()
        merged_articles = self._merge_articles_for_full_output(previous, updated_articles)
        merged_dicts = [a.to_dict() for a in merged_articles]

        if len(merged_articles) > len(updated_articles):
            print(
                f"Saída agregada: {len(merged_articles)} artigo(s) no total "
                f"({len(updated_articles)} deste lote + "
                f"{len(merged_articles) - len(updated_articles)} de execuções anteriores).",
                flush=True,
            )

        JsonLogger.print_json(
            "articles_metadata_apos_do_field_completion", merged_dicts
        )

        csv_writer = CsvWriter(
            self.csv_save_dir, "Artigos.csv", "Autores.csv", "Referencias.csv", antes=False
        )
        csv_writer.write_dicts_to_csv(merged_articles)

        self.write_csv_by_workshop(merged_articles)

        return merged_articles

    def update_pages(self, first_page, num_pages):
        """
        Updates the pages field based on first page and number of pages.

        Args:
            first_page (str): First page number as a string.
            num_pages (int): Number of pages.

        Returns:
            str: Updated pages field.
        """
        if first_page and first_page.isdigit():
            first_page_int = int(first_page)
            if num_pages == 1:
                return str(first_page_int)
            else:
                last_page = first_page_int + int(num_pages) - 1
                return f"{first_page_int}-{last_page}"
        else:
            return first_page

    def _normalize_doi(self, doi):
        """
        Normalizes a DOI by removing URL prefixes, keeping only the identifier.

        Args:
            doi (str): DOI string that may include URL prefix.

        Returns:
            str: Normalized DOI identifier (e.g., "10.5753/cbie.wcbie.2019.1")
        """
        if not doi:
            return ""

        # Remove http://, https://, dx.doi.org/, doi.org/ prefixes
        normalized = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip())
        return normalized

    def _infer_doi_prefix(self, dois):
        """
        Infers the DOI base prefix (without year/suffix) from a list of extracted DOIs.

        Args:
            dois (list): List of DOI strings.

        Returns:
            str: Inferred DOI prefix (without the suffix part), or None if cannot infer.
        """
        if not dois:
            return None

        # Normalize DOIs - remove https://doi.org/ prefix if present
        normalized_dois = []
        for doi in dois:
            if not doi:
                continue
            # Remove http/https and doi.org prefixes
            normalized = self._normalize_doi(doi)
            if normalized:
                normalized_dois.append(normalized)

        if not normalized_dois:
            return None

        # Find common base prefix pattern
        # For DOIs like: 10.xxxx/prefix.year.suffix
        # we want to extract a base prefix without year/suffix: 10.xxxx/prefix.
        prefix_patterns = []
        for doi in normalized_dois:
            if "/" not in doi:
                continue

            main_prefix, suffix_part = doi.split("/", 1)
            parts = [p for p in suffix_part.split(".") if p]

            # We expect at least: prefix.year.suffix
            if len(parts) >= 3:
                base_suffix = ".".join(parts[:-2])
            elif len(parts) >= 1:
                # Fallback: use only the first part after the slash
                base_suffix = parts[0]
            else:
                continue

            prefix_patterns.append(f"{main_prefix}/{base_suffix}.")

        if not prefix_patterns:
            return None

        # Find the most common prefix pattern
        from collections import Counter

        prefix_counts = Counter(prefix_patterns)
        most_common = prefix_counts.most_common(1)[0][0]

        # Return normalized prefix (without URL) - just the identifier pattern
        return most_common

    def correct_doi(self, article):
        """
        Corrects or generates the DOI field in the article.
        Uses extracted DOI if available, otherwise generates one using prefix.
        Always stores DOI in normalized format (identifier only, no URL).

        Args:
            article (Article): Article object to correct.
        """
        # If DOI already exists, normalize it and return
        if hasattr(article, "doi") and article.doi and article.doi.strip():
            article.doi = self._normalize_doi(article.doi)
            return

        # Only generate DOI if we have prefix and first_page
        # Prefer the prefix inferred from the website and use the config value as fallback
        doi_prefix = self.inferred_doi_prefix or self.doi_prefix

        if not doi_prefix:
            print(
                "Aviso: Não foi possível gerar DOI - prefixo não disponível e não foi possível inferir."
            )
            return

        if hasattr(article, "first_page") and article.first_page:
            # Normalize prefix (remove URL if present)
            clean_prefix = self._normalize_doi(doi_prefix)
            if not clean_prefix:
                # If prefix was in URL format, try to extract from it
                clean_prefix = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_prefix)
            clean_prefix = clean_prefix.rstrip("/")

            # Generate DOI in normalized format (identifier only, no URL)
            generated_doi = f"{clean_prefix}{self.year}.{article.first_page}"
            article.doi = generated_doi

    def write_csv_by_workshop(self, articles_list):
        """
        Writes CSV files separated by workshop/section.

        Args:
            articles_list (list): List of Article objects.
        """
        # Group articles by section
        workshops = {}
        for article in articles_list:
            section = (
                article.section_abbrev
                if hasattr(article, "section_abbrev")
                else article.to_dict().get("sectionAbbrev", "UNKNOWN")
            )

            if section not in workshops:
                workshops[section] = []
            workshops[section].append(article)

        # Create CSV files for each workshop
        for workshop_name, workshop_articles in workshops.items():
            if not workshop_articles:
                continue

            # Create subdirectory for workshop
            workshop_dir = os.path.join(self.csv_save_dir, "por_workshop")

            csv_writer = CsvWriter(
                workshop_dir,
                f"{workshop_name}_Artigos.csv",
                f"{workshop_name}_Autores.csv",
                f"{workshop_name}_Referencias.csv",
                antes=False,
            )
            csv_writer.write_dicts_to_csv(workshop_articles)

        print(
            f"\nCSV files by workshop created in {os.path.join(self.csv_save_dir, 'por_workshop')}"
        )
        print(f"Total workshops processed: {len(workshops)}")
