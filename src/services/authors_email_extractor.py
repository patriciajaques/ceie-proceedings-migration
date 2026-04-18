import json
import os
import re
import unicodedata
from typing import Any, Dict, Tuple

import pandas as pd

from src.config.config_loader import ConfigLoader
from src.domain.article import Article

# Max chars of PDF text preview sent to the affiliation+email LLM (first page only).
_AFFILIATION_EMAIL_TEXT_PREVIEW_MAX = 12000

# Number of PDF pages to send for author enrichment (first page only).
AFFILIATION_EMAIL_PAGE_COUNT = 1


class AuthorsEmailExtractor:
    """
    Helpers for author e-mail, affiliation, and country enrichment.

    Includes CSV/JSON backfill from logs and LLM-based extraction from PDFs
    (:meth:`apply_affiliation_email_llm_to_article_objects`).
    """

    def __init__(self, config_loader: ConfigLoader) -> None:
        """
        Initialize the extractor with injected configuration.

        Args:
            config_loader: Configuration loader instance.
        """
        self.config_loader = config_loader

        output_dir = config_loader.get_config_value("output_dir")
        self.year = str(config_loader.get_config_value("year"))

        self.csv_folder = os.path.join(output_dir, self.year, "csv")
        self.logs_folder = os.path.join(output_dir, self.year, "logs")
        self.pdf_folder = os.path.join(output_dir, self.year, "pdfs")

    def _get_authors_csv_path(self) -> str:
        return os.path.join(self.csv_folder, "Autores.csv")

    def _get_metadata_json_path(self) -> str:
        return os.path.join(
            self.logs_folder,
            "articles_metadata_antes_do_field_completion.json",
        )

    def _get_website_cache_path(self) -> str:
        return os.path.join(self.logs_folder, "website_articles_cache.json")

    def load_authors_df(self) -> pd.DataFrame:
        """
        Load authors data from Autores.csv.

        Returns:
            DataFrame with authors data.
        """
        csv_path = self._get_authors_csv_path()
        return pd.read_csv(
            csv_path,
            delimiter=";",
            keep_default_na=False,
            na_values=[],
        )

    def load_articles_metadata(self) -> list[Dict[str, Any]]:
        """
        Load articles metadata JSON file.

        Returns:
            List of article metadata dictionaries.
        """
        json_path = self._get_metadata_json_path()
        if not os.path.exists(json_path):
            return []

        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_website_cache(self) -> list[Dict[str, Any]]:
        """
        Load website articles cache (from OJS scrape) if it exists.

        Returns:
            List of article dicts with idJEMS and authors.
        """
        path = self._get_website_cache_path()
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _normalize_name(first: str, middle: str, last: str) -> str:
        """
        Build a normalized full name used as matching key.

        Args:
            first: First name.
            middle: Middle name (may be empty).
            last: Last name.

        Returns:
            Normalized full name (lowercase, without accents, single spaces).
        """
        parts = [p.strip() for p in [first, middle, last] if p and str(p).strip()]
        full = " ".join(parts)
        nfkd = unicodedata.normalize("NFKD", full)
        no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
        normalized = " ".join(no_accents.lower().split())
        return normalized

    def build_email_index_from_metadata(
        self,
        articles_metadata: list[Dict[str, Any]],
    ) -> Dict[Tuple[str, str], str]:
        """
        Build an index of emails from articles metadata.

        Key is (article_id_as_str, normalized_full_name).

        Args:
            articles_metadata: List of article metadata dictionaries.

        Returns:
            Dictionary mapping (article_id, normalized_name) to email.
        """
        index: Dict[Tuple[str, str], str] = {}

        for article in articles_metadata:
            article_id = str(
                article.get("id_jems")
                or article.get("idJEMS")
                or article.get("id")
                or ""
            ).strip()
            if not article_id:
                continue

            authors = article.get("authors") or []
            for a in authors:
                email = (a.get("authorEmail") or "").strip()
                if not email:
                    continue

                first = a.get("authorFirstName") or ""
                middle = a.get("authorMiddleName") or ""
                last = a.get("authorLastName") or ""

                normalized_name = self._normalize_name(first, middle, last)
                if not normalized_name:
                    continue

                key = (article_id, normalized_name)

                # Keep first seen email, do not overwrite silently
                if key not in index:
                    index[key] = email

        return index

    def build_email_index_from_website_cache(
        self,
        cache: list[Dict[str, Any]],
    ) -> Dict[Tuple[str, str], str]:
        """
        Build email index from website_articles_cache (same key: idJEMS, normalized_name).
        """
        index: Dict[Tuple[str, str], str] = {}
        for article in cache:
            article_id = str(
                article.get("idJEMS") or article.get("id_jems") or ""
            ).strip()
            if not article_id:
                continue
            for a in article.get("authors") or []:
                email = (a.get("authorEmail") or "").strip()
                if not email:
                    continue
                first = a.get("authorFirstName") or ""
                middle = a.get("authorMiddleName") or ""
                last = a.get("authorLastName") or ""
                normalized_name = self._normalize_name(first, middle, last)
                if not normalized_name:
                    continue
                key = (article_id, normalized_name)
                if key not in index:
                    index[key] = email
        return index

    def fill_missing_emails(self) -> pd.DataFrame:
        """
        Fill missing authorEmail in Autores.csv from metadata JSON and/or
        website_articles_cache (when available). CSV article column is
        sequential (1-based); idJEMS is taken from the same order in metadata.
        """
        authors_df = self.load_authors_df()

        if authors_df.empty:
            return authors_df

        articles_metadata = self.load_articles_metadata()
        # Article number in CSV (1, 2, 3...) maps to idJEMS by list order
        ordered_id_jems = [
            str(a.get("idJEMS") or a.get("id_jems") or "").strip()
            for a in articles_metadata
        ]

        email_index = self.build_email_index_from_metadata(articles_metadata)
        website_cache = self.load_website_cache()
        if website_cache:
            cache_index = self.build_email_index_from_website_cache(website_cache)
            email_index = {**email_index, **cache_index}
            print("Cache do website (website_articles_cache.json) usado como fonte.")
        if not email_index:
            print(
                "Nenhum e-mail encontrado em metadados nem no cache do website."
            )
            return authors_df

        original_non_empty = (
            authors_df["authorEmail"].astype(str).str.strip().ne("").sum()
        )
        filled_count = 0

        def fill_email(row: pd.Series) -> str:
            nonlocal filled_count
            current_email = str(row.get("authorEmail") or "").strip()
            if current_email and current_email.lower() != "nan":
                return current_email
            try:
                article_num = int(row.get("article") or 0)
            except (TypeError, ValueError):
                return current_email
            if not (1 <= article_num <= len(ordered_id_jems)):
                return current_email
            id_jems = ordered_id_jems[article_num - 1]
            normalized_name = self._normalize_name(
                str(row.get("authorFirstName") or ""),
                str(row.get("authorMiddleName") or ""),
                str(row.get("authorLastName") or ""),
            )
            if not id_jems or not normalized_name:
                return current_email
            key = (id_jems, normalized_name)
            new_email = email_index.get(key, "").strip()
            if new_email:
                filled_count += 1
                return new_email
            return current_email

        authors_df["authorEmail"] = authors_df.apply(fill_email, axis=1)
        total_non_empty_after = (
            authors_df["authorEmail"].astype(str).str.strip().ne("").sum()
        )
        print(
            f"E-mails já preenchidos originalmente: {original_non_empty} | "
            f"Preenchidos a partir de JSON/cache: {filled_count} | "
            f"Total com e-mail após preenchimento: {total_non_empty_after}"
        )
        return authors_df

    @staticmethod
    def _truncate_at_resumo_or_abstract(text: str) -> str:
        """
        Return text only up to (and not including) the first section heading
        Resumo, Resumen or Abstract (whichever comes first), so the LLM
        receives only the front matter where author emails usually appear.
        """
        if not text or not text.strip():
            return text
        # Match start of line (or start of text) followed by Resumo/Abstract/Resumen
        # with optional punctuation (e.g. "Resumo.", "Abstract.", "Resumo:")
        pattern = re.compile(
            r"^(?:\s*)(?:Resumo|Resumen|Abstract)\s*[.:]?\s*",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(text)
        if match:
            head = text[: match.start()].rstrip()
            # If Resumo/Abstract appears at the very start, keep full text so we do
            # not send an empty excerpt to the LLM.
            if not head:
                return text
            return head
        return text

    @staticmethod
    def _affiliation_no_extracted_text_preview(
        title_orig: str,
        title_en: str,
        id_jems: str,
    ) -> str:
        """
        Prompt body when PyMuPDF extracts no text (e.g. image-only cover PDF).
        """
        title = (title_orig or title_en or "").strip() or "(no title in metadata)"
        return (
            "[No text could be extracted from this PDF (e.g. image-only pages).]\n"
            f"idJEMS: {id_jems}\n"
            f"Metadata title: {title}\n\n"
            "Context: SBIE proceedings editorial material, Brazilian Computer "
            "Society (SBC). For each author in the given order, return plausible "
            "institutional affiliations in Portuguese and English (acronyms in "
            "parentheses when usual). For cover credits without a clear school, "
            "use an affiliation consistent with SBC / proceedings editorial role."
        )

    @staticmethod
    def _expand_brace_emails(emails_list: list[str]) -> list[str]:
        """
        Expand patterns like {user1, user2}@domain.com into separate emails
        (user1@domain.com, user2@domain.com). Flattens the list in order.
        """
        result: list[str] = []
        for s in emails_list:
            s = (s or "").strip()
            if not s:
                result.append("")
                continue
            # Match { part1, part2, ... }@domain
            brace = re.search(r"\{([^}]+)\}(@[\w.-]+\.[a-zA-Z]+)", s)
            if brace:
                parts = [p.strip() for p in brace.group(1).split(",") if p.strip()]
                domain = brace.group(2)
                for part in parts:
                    result.append(part + domain)
            else:
                result.append(s)
        return result

    @staticmethod
    def _cell_str(val: Any) -> str:
        """Return non-empty string; treat NaN and 'nan' as empty."""
        s = str(val).strip() if val is not None and val != "" else ""
        return "" if s.lower() == "nan" else s

    @staticmethod
    def _rows_for_article(article_series: pd.Series, article_num: int) -> pd.Series:
        """
        Boolean mask for rows whose ``article`` column matches article_num.

        Robust to CSV dtypes (int, str like '11', or float from bad reads).
        """
        coerced = pd.to_numeric(article_series, errors="coerce")
        return coerced == int(article_num)

    _AUTHORS_CSV_COLUMN_ORDER: list[str] = [
        "article",
        "authorFirstName",
        "authorMiddleName",
        "authorLastName",
        "authorAffiliation",
        "authorAffiliationEn",
        "authorCountry",
        "authorEmail",
        "orcid",
        "order",
    ]

    def _save_authors_dataframe(
        self,
        authors_df: pd.DataFrame,
        filename: str,
    ) -> None:
        """Write authors DataFrame to csv_folder with standard column order."""
        if authors_df.empty:
            print("DataFrame de autores vazio. Nada foi salvo.")
            return

        desired_order = self._AUTHORS_CSV_COLUMN_ORDER
        columns = [c for c in desired_order if c in authors_df.columns]
        other_columns = [c for c in authors_df.columns if c not in columns]
        final_df = (
            authors_df[columns + other_columns].copy()
            if other_columns
            else authors_df[columns].copy()
        )
        final_df = final_df.fillna("")

        output_path = os.path.join(self.csv_folder, filename)
        final_df.to_csv(output_path, sep=";", index=False)
        print(f"Arquivo salvo em: {output_path}")

    @staticmethod
    def _normalize_country_display(raw: str) -> str:
        """Return country as returned by the LLM (full name); strip only."""
        return (raw or "").strip()

    @staticmethod
    def _parse_llm_affiliation_email_json(
        response: str,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        """
        Parse LLM response with affiliations_pt, affiliations_en, countries, emails.

        Returns:
            Four parallel lists; empty lists on failure.
        """
        if not response or not response.strip():
            return [], [], [], []
        text = response.strip()
        if "```" in text:
            for part in re.split(r"```\w*\s*", text):
                part = part.strip()
                if part.startswith("{"):
                    text = part
                    break
        start = text.find("{")
        if start == -1:
            return [], [], [], []
        depth = 0
        for i, c in enumerate(text[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : i + 1])
                        pt_raw = data.get("affiliations_pt") or []
                        en_raw = data.get("affiliations_en") or []
                        co_raw = data.get("countries") or []
                        em_raw = data.get("emails") or []
                        pt_list = [
                            str(a).strip() if a is not None else ""
                            for a in pt_raw
                        ]
                        en_list = [
                            str(a).strip() if a is not None else ""
                            for a in en_raw
                        ]
                        co_list = [
                            AuthorsEmailExtractor._normalize_country_display(
                                str(a) if a is not None else ""
                            )
                            for a in co_raw
                        ]
                        em_list = [
                            str(e).strip() if e is not None else ""
                            for e in em_raw
                        ]
                        return pt_list, en_list, co_list, em_list
                    except (json.JSONDecodeError, TypeError):
                        return [], [], [], []
        return [], [], [], []

    def fill_missing_emails_from_llm(
        self,
        ai_client: Any,
        pdf_processor: Any,
        max_pages_per_pdf: int = 1,
        start_df: pd.DataFrame | None = None,
        max_articles: int | None = None,
    ) -> pd.DataFrame:
        """
        Fill missing authorEmail via LLM. Delegates to
        :meth:`fill_affiliation_email_from_llm` (single call also fills
        affiliations and country when needed).
        """
        return self.fill_affiliation_email_from_llm(
            ai_client,
            pdf_processor,
            max_pages_per_pdf,
            start_df,
            max_articles,
        )

    def fill_affiliations_from_llm(
        self,
        ai_client: Any,
        pdf_processor: Any,
        max_pages_per_pdf: int = 1,
        start_df: pd.DataFrame | None = None,
        max_articles: int | None = None,
    ) -> pd.DataFrame:
        """
        Fill affiliations via LLM. Delegates to
        :meth:`fill_affiliation_email_from_llm` (single call also fills email).
        """
        return self.fill_affiliation_email_from_llm(
            ai_client,
            pdf_processor,
            max_pages_per_pdf,
            start_df,
            max_articles,
        )

    def fill_affiliation_email_from_llm(
        self,
        ai_client: Any,
        pdf_processor: Any,
        max_pages_per_pdf: int = 1,
        start_df: pd.DataFrame | None = None,
        max_articles: int | None = None,
    ) -> pd.DataFrame:
        """
        Fill authorAffiliation, authorAffiliationEn, authorCountry, and authorEmail
        from PDFs using one LLM call per article (``author_affiliation_email_extraction``).

        Uses the first PDF page only, truncated before Resumo/Abstract. Overwrites
        affiliation fields when the LLM returns a non-empty value; fills email only
        when the cell is empty.
        """
        _ = max_pages_per_pdf
        pages_take = AFFILIATION_EMAIL_PAGE_COUNT
        authors_df = start_df if start_df is not None else self.load_authors_df()
        if authors_df.empty:
            return authors_df

        articles_metadata = self.load_articles_metadata()
        ordered_id_jems = [
            str(a.get("idJEMS") or a.get("id_jems") or "").strip()
            for a in articles_metadata
        ]
        if not ordered_id_jems:
            print(
                "Nenhum metadado de artigos encontrado. "
                "Abortando extração de afiliações/e-mails por LLM."
            )
            return authors_df

        total_articles = len(ordered_id_jems)
        article_num_col = authors_df["article"]

        for idx, id_jems in enumerate(ordered_id_jems):
            if max_articles is not None and idx >= max_articles:
                break
            if not id_jems:
                continue
            article_num = idx + 1
            mask = self._rows_for_article(article_num_col, article_num)
            article_rows = authors_df.loc[mask].sort_values("order")
            if article_rows.empty:
                continue

            author_display_names: list[str] = []
            row_indices: list[int] = []
            for row_index, row in article_rows.iterrows():
                first = self._cell_str(row.get("authorFirstName"))
                middle = self._cell_str(row.get("authorMiddleName"))
                last = self._cell_str(row.get("authorLastName"))
                name_display = " ".join(p for p in [first, middle, last] if p)
                if not name_display:
                    continue
                author_display_names.append(name_display)
                row_indices.append(row_index)

            if not author_display_names:
                continue

            pdf_path = os.path.join(self.pdf_folder, f"{id_jems}.pdf")
            if not os.path.isfile(pdf_path):
                continue

            try:
                text_pages, _ = pdf_processor.extract_text_from_each_page(pdf_path)
                text_pages = text_pages[:pages_take] if text_pages else []
                combined_text = "\n\n".join(p if p else "" for p in text_pages)
                use_fallback = not combined_text.strip()
                if not use_fallback:
                    combined_text = self._truncate_at_resumo_or_abstract(
                        combined_text
                    )
                    if not combined_text.strip():
                        use_fallback = True
            except Exception as e:
                print(f"  Erro ao extrair texto do PDF {id_jems}: {e}")
                continue

            authors_block = "Autores (na ordem abaixo):\n" + "\n".join(
                f"{i+1}. {name}" for i, name in enumerate(author_display_names)
            )
            if use_fallback:
                title_orig = ""
                title_en = ""
                for meta in articles_metadata:
                    if (
                        str(meta.get("idJEMS") or meta.get("id_jems") or "").strip()
                        == id_jems
                    ):
                        title_orig = str(meta.get("titleOrig") or "")
                        title_en = str(meta.get("titleEn") or "")
                        break
                text_preview = self._affiliation_no_extracted_text_preview(
                    title_orig, title_en, id_jems
                )
            else:
                text_preview = (
                    combined_text[:_AFFILIATION_EMAIL_TEXT_PREVIEW_MAX]
                    if len(combined_text) > _AFFILIATION_EMAIL_TEXT_PREVIEW_MAX
                    else combined_text
                )
            instruction = (
                f"{authors_block}\n\n"
                "--- Texto do artigo (primeira página, até Resumo/Abstract) ---\n\n"
                f"{text_preview}\n\n"
                "--- Fim do texto ---\n\n"
                "Com base nas instruções na mensagem de sistema e NO TEXTO ACIMA, "
                "retorne apenas o objeto JSON com affiliations_pt, affiliations_en, "
                "countries e emails.\n"
            )

            tag = " (sem texto no PDF; inferência por metadados)" if use_fallback else ""
            print(
                f"  [LLM] Afiliações/país/e-mails (artigo "
                f"{idx + 1}/{total_articles}, idJEMS={id_jems}){tag}..."
            )
            try:
                response = ai_client.create_completion(instruction, is_json=True)
            except Exception as e:
                print(f"  Erro na chamada à IA para {id_jems}: {e}")
                continue

            affiliations_pt, affiliations_en, countries, emails_list = (
                self._parse_llm_affiliation_email_json(response or "")
            )
            emails_list = self._expand_brace_emails(emails_list)

            n_authors = len(author_display_names)
            if len(affiliations_pt) < n_authors:
                affiliations_pt = affiliations_pt + [""] * (
                    n_authors - len(affiliations_pt)
                )
            if len(affiliations_en) < n_authors:
                affiliations_en = affiliations_en + [""] * (
                    n_authors - len(affiliations_en)
                )
            if len(countries) < n_authors:
                countries = countries + [""] * (n_authors - len(countries))
            if len(emails_list) < n_authors:
                emails_list = emails_list + [""] * (
                    n_authors - len(emails_list)
                )

            affiliations_pt = affiliations_pt[:n_authors]
            affiliations_en = affiliations_en[:n_authors]
            countries = countries[:n_authors]
            emails_list = emails_list[:n_authors]

            for pos, row_index in enumerate(row_indices):
                new_pt = self._cell_str(
                    affiliations_pt[pos] if pos < len(affiliations_pt) else ""
                )
                new_en = self._cell_str(
                    affiliations_en[pos] if pos < len(affiliations_en) else ""
                )
                new_co = self._cell_str(
                    countries[pos] if pos < len(countries) else ""
                )
                if new_pt:
                    authors_df.at[row_index, "authorAffiliation"] = new_pt
                if new_en:
                    authors_df.at[row_index, "authorAffiliationEn"] = new_en
                if new_co and "authorCountry" in authors_df.columns:
                    authors_df.at[row_index, "authorCountry"] = new_co

                email = (emails_list[pos] if pos < len(emails_list) else "").strip()
                if email and "@" in email:
                    current = self._cell_str(
                        authors_df.at[row_index, "authorEmail"]
                    )
                    if not current:
                        authors_df.at[row_index, "authorEmail"] = email

        return authors_df

    def apply_affiliation_email_llm_to_article_objects(
        self,
        articles: list[Article],
        ai_client: Any,
        pdf_processor: Any,
        max_pages_per_pdf: int = 1,
    ) -> None:
        """
        Fill author affiliation, country (full name), and email using one LLM call
        per article. Uses the first PDF page only, truncated before Resumo/Abstract.

        Skips an article when every author already has pt/en affiliation, country,
        and email. Email is only written when the field was empty.

        Args:
            articles: Articles to enrich in place.
            ai_client: Client with ``author_affiliation_email_extraction`` prompt.
            pdf_processor: PDF text extraction helper.
            max_pages_per_pdf: Ignored; kept for API compatibility. Only the first
                page is used (see ``AFFILIATION_EMAIL_PAGE_COUNT``).
        """
        _ = max_pages_per_pdf
        if not articles:
            return

        pages_take = AFFILIATION_EMAIL_PAGE_COUNT
        total = len(articles)

        for idx, article in enumerate(articles):
            id_jems = (getattr(article, "id_jems", None) or "").strip()
            if not id_jems:
                continue

            authors_list = list(getattr(article, "authors", None) or [])
            if not authors_list:
                continue

            sorted_authors = sorted(
                authors_list,
                key=lambda a: int(getattr(a, "order", 0) or 0),
            )
            needs_aff = False
            needs_email = False
            for auth in sorted_authors:
                pt = self._cell_str(getattr(auth, "affiliation", None))
                en = self._cell_str(getattr(auth, "affiliation_en", None))
                co = self._cell_str(getattr(auth, "country", None))
                if not pt or not en or not co:
                    needs_aff = True
                em = self._cell_str(getattr(auth, "email", None))
                if not em:
                    needs_email = True
            if not needs_aff and not needs_email:
                continue

            author_pairs: list[tuple[Any, str]] = []
            for auth in sorted_authors:
                first = self._cell_str(getattr(auth, "first_name", None))
                middle = self._cell_str(getattr(auth, "middle_name", None))
                last = self._cell_str(getattr(auth, "last_name", None))
                name_display = " ".join(p for p in [first, middle, last] if p)
                if name_display:
                    author_pairs.append((auth, name_display))
            if not author_pairs:
                continue
            author_display_names = [p[1] for p in author_pairs]

            pdf_path = os.path.join(self.pdf_folder, f"{id_jems}.pdf")
            if not os.path.isfile(pdf_path):
                continue

            try:
                text_pages, _ = pdf_processor.extract_text_from_each_page(pdf_path)
                text_pages = text_pages[:pages_take] if text_pages else []
                combined_text = "\n\n".join(p if p else "" for p in text_pages)
                use_fallback = not combined_text.strip()
                if not use_fallback:
                    combined_text = self._truncate_at_resumo_or_abstract(
                        combined_text
                    )
                    if not combined_text.strip():
                        use_fallback = True
            except Exception as e:
                print(f"  Erro ao extrair texto do PDF {id_jems}: {e}")
                continue

            authors_block = "Autores (na ordem abaixo):\n" + "\n".join(
                f"{i+1}. {name}" for i, name in enumerate(author_display_names)
            )
            if use_fallback:
                title_orig = str(getattr(article, "title_orig", None) or "")
                title_en = str(getattr(article, "title_en", None) or "")
                text_preview = self._affiliation_no_extracted_text_preview(
                    title_orig, title_en, id_jems
                )
            else:
                text_preview = (
                    combined_text[:_AFFILIATION_EMAIL_TEXT_PREVIEW_MAX]
                    if len(combined_text) > _AFFILIATION_EMAIL_TEXT_PREVIEW_MAX
                    else combined_text
                )
            instruction = (
                f"{authors_block}\n\n"
                "--- Texto do artigo (primeira página, até Resumo/Abstract) ---\n\n"
                f"{text_preview}\n\n"
                "--- Fim do texto ---\n\n"
                "Com base nas instruções na mensagem de sistema e NO TEXTO ACIMA, "
                "retorne apenas o objeto JSON com affiliations_pt, affiliations_en, "
                "countries e emails.\n"
            )

            tag = " (sem texto no PDF)" if use_fallback else ""
            print(
                f"  [LLM] Afiliações/país/e-mails (artigo {idx + 1}/{total}, "
                f"idJEMS={id_jems}){tag}...",
                flush=True,
            )
            try:
                response = ai_client.create_completion(instruction, is_json=True)
            except Exception as e:
                print(f"  Erro na chamada à IA para {id_jems}: {e}")
                continue

            affiliations_pt, affiliations_en, countries, emails_list = (
                self._parse_llm_affiliation_email_json(response or "")
            )
            emails_list = self._expand_brace_emails(emails_list)

            n_authors = len(author_display_names)
            if len(affiliations_pt) < n_authors:
                affiliations_pt = affiliations_pt + [""] * (
                    n_authors - len(affiliations_pt)
                )
            if len(affiliations_en) < n_authors:
                affiliations_en = affiliations_en + [""] * (
                    n_authors - len(affiliations_en)
                )
            if len(countries) < n_authors:
                countries = countries + [""] * (n_authors - len(countries))
            if len(emails_list) < n_authors:
                emails_list = emails_list + [""] * (
                    n_authors - len(emails_list)
                )

            affiliations_pt = affiliations_pt[:n_authors]
            affiliations_en = affiliations_en[:n_authors]
            countries = countries[:n_authors]
            emails_list = emails_list[:n_authors]

            for pos, (auth, _) in enumerate(author_pairs):
                if pos >= n_authors:
                    break
                new_pt = self._cell_str(
                    affiliations_pt[pos] if pos < len(affiliations_pt) else ""
                )
                new_en = self._cell_str(
                    affiliations_en[pos] if pos < len(affiliations_en) else ""
                )
                new_co = self._cell_str(
                    countries[pos] if pos < len(countries) else ""
                )
                if new_pt:
                    auth.affiliation = new_pt
                if new_en:
                    auth.affiliation_en = new_en
                if new_co:
                    auth.country = new_co

                email = (emails_list[pos] if pos < len(emails_list) else "").strip()
                if email and "@" in email:
                    current = self._cell_str(getattr(auth, "email", None))
                    if not current:
                        auth.email = email

    def save_autores_csv(self, authors_df: pd.DataFrame) -> None:
        """
        Save authors DataFrame to the canonical Autores.csv for the configured year.

        Use after e-mail/affiliation enrichment so downstream tools read one file.
        """
        self._save_authors_dataframe(authors_df, "Autores.csv")

    def save_authors_emails_export(self, authors_df: pd.DataFrame) -> None:
        """
        Save updated authors DataFrame to Autores_emails_{year}.csv.

        Args:
            authors_df: DataFrame with updated authorEmail values.
        """
        self._save_authors_dataframe(
            authors_df,
            f"Autores_emails_{self.year}.csv",
        )

    def save_authors_affiliations_export(self, authors_df: pd.DataFrame) -> None:
        """
        Save updated authors DataFrame with affiliations to
        Autores_afiliacoes_{year}.csv.

        Args:
            authors_df: DataFrame with updated affiliation values.
        """
        self._save_authors_dataframe(
            authors_df,
            f"Autores_afiliacoes_{self.year}.csv",
        )

