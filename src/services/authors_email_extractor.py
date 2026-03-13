import json
import os
import re
import unicodedata
from typing import Any, Dict, Tuple

import pandas as pd

from src.config.config_loader import ConfigLoader


class AuthorsEmailExtractor:
    """
    Service responsible for filling authorEmail in Autores.csv.

    This first version only reuses structured metadata from JSON logs,
    without calling any AI service.
    """

    def __init__(self, config_loader: ConfigLoader) -> None:
        """
        Initialize the extractor with injected configuration.

        Args:
            config_loader: Configuration loader instance.
        """
        self.config_loader = config_loader

        output_dir = config_loader.get_config_value("output_dir")
        year = str(config_loader.get_config_value("year"))

        self.csv_folder = os.path.join(output_dir, year, "csv")
        self.logs_folder = os.path.join(output_dir, year, "logs")
        self.pdf_folder = os.path.join(output_dir, year, "pdfs")

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
            return text[: match.start()].rstrip()
        return text

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
    def _parse_llm_emails_json(response: str) -> list[str]:
        """Parse LLM response to extract emails list (same order as authors). Returns [] on failure."""
        if not response or not response.strip():
            return []
        text = response.strip()
        if "```" in text:
            for part in re.split(r"```\w*\s*", text):
                part = part.strip()
                if part.startswith("{"):
                    text = part
                    break
        start = text.find("{")
        if start == -1:
            return []
        depth = 0
        for i, c in enumerate(text[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : i + 1])
                        raw = data.get("emails") or []
                        return [str(e).strip() if e else "" for e in raw]
                    except (json.JSONDecodeError, TypeError):
                        return []
        return []

    def fill_missing_emails_from_llm(
        self,
        ai_client: Any,
        pdf_processor: Any,
        max_pages_per_pdf: int = 5,
        start_df: pd.DataFrame | None = None,
        max_articles: int | None = None,
    ) -> pd.DataFrame:
        """
        Fill missing authorEmail by extracting from article PDFs using an LLM.

        For each article (by idJEMS), extracts text from the first max_pages_per_pdf
        pages (truncated at Resumo/Abstract for this step only), sends to the AI
        client (author_email_extraction prompt), and merges the extracted emails
        into the authors DataFrame. Only fills cells that are currently empty.

        Args:
            ai_client: AI client with create_completion(user_message, is_json=True).
            pdf_processor: PDFProcessor instance (directory set to self.pdf_folder).
            max_pages_per_pdf: Number of initial PDF pages to send to the LLM.
            start_df: Optional DataFrame to start from (e.g. already filled from
                JSON/cache). If None, loads from Autores.csv.
            max_articles: If set, process only the first max_articles articles
                (for testing). None = process all.

        Returns:
            DataFrame with updated authorEmail where the LLM found emails.
        """
        authors_df = start_df if start_df is not None else self.load_authors_df()
        if authors_df.empty:
            return authors_df

        articles_metadata = self.load_articles_metadata()
        ordered_id_jems = [
            str(a.get("idJEMS") or a.get("id_jems") or "").strip()
            for a in articles_metadata
        ]
        if not ordered_id_jems:
            print("Nenhum metadado de artigos encontrado. Abortando extração por LLM.")
            return authors_df

        email_index: Dict[Tuple[str, str], str] = {}
        total_articles = len(ordered_id_jems)
        pages_config = max_pages_per_pdf if max_pages_per_pdf > 0 else 5
        article_num_col = authors_df["article"]

        def _cell_str(val: Any) -> str:
            """Return non-empty string; treat NaN and 'nan' as empty."""
            s = str(val).strip() if val is not None and val != "" else ""
            return "" if s.lower() == "nan" else s

        for idx, id_jems in enumerate(ordered_id_jems):
            if max_articles is not None and idx >= max_articles:
                break
            if not id_jems:
                continue
            article_num = idx + 1
            # Authors for this article (we already have them), in order
            mask = article_num_col == article_num
            article_rows = authors_df.loc[mask].sort_values("order")
            if article_rows.empty:
                continue
            author_keys: list[Tuple[str, str]] = []
            author_names_display: list[str] = []
            for _, row in article_rows.iterrows():
                first = _cell_str(row.get("authorFirstName"))
                middle = _cell_str(row.get("authorMiddleName"))
                last = _cell_str(row.get("authorLastName"))
                normalized = self._normalize_name(first, middle, last)
                if normalized:
                    author_keys.append((id_jems, normalized))
                    author_names_display.append(
                        " ".join(p for p in [first, middle, last] if p)
                    )
            if not author_keys:
                continue

            pdf_path = os.path.join(self.pdf_folder, f"{id_jems}.pdf")
            if not os.path.isfile(pdf_path):
                continue
            try:
                text_pages, _ = pdf_processor.extract_text_from_each_page(pdf_path)
                text_pages = text_pages[:pages_config] if text_pages else []
                combined_text = "\n\n".join(p if p else "" for p in text_pages)
                if not combined_text.strip():
                    continue
                # For email extraction, use only text up to Resumo/Abstract
                combined_text = self._truncate_at_resumo_or_abstract(combined_text)
                if not combined_text.strip():
                    continue
            except Exception as e:
                print(f"  Erro ao extrair texto do PDF {id_jems}: {e}")
                continue

            authors_block = "Autores (na ordem abaixo):\n" + "\n".join(
                f"{i+1}. {name}" for i, name in enumerate(author_names_display)
            )
            text_preview = (
                combined_text[:12000]
                if len(combined_text) > 12000
                else combined_text
            )
            instruction = (
                f"{authors_block}\n\n"
                "--- Texto do artigo (até Resumo/Abstract) ---\n\n"
                f"{text_preview}\n\n"
                "--- Fim do texto ---\n\n"
                'Retorne apenas um JSON com a chave "emails": uma lista de strings com o e-mail de cada autor na mesma ordem (use "" se não encontrar).'
            )
            print(
                f"  [LLM] Extraindo e-mails do artigo {idx + 1}/{total_articles} (idJEMS={id_jems})..."
            )
            try:
                response = ai_client.create_completion(instruction, is_json=True)
            except Exception as e:
                print(f"  Erro na chamada à IA para {id_jems}: {e}")
                continue
            emails_list = self._parse_llm_emails_json(response or "")
            emails_list = self._expand_brace_emails(emails_list)
            # Align with author order: first N emails for N authors (pad with "" if needed)
            n_authors = len(author_keys)
            for i in range(n_authors):
                email = (emails_list[i] if i < len(emails_list) else "").strip()
                if email and "@" in email:
                    key = author_keys[i]
                    if key not in email_index:
                        email_index[key] = email

        if not email_index:
            print("Nenhum e-mail extraído pela LLM.")
            return authors_df

        original_non_empty = (
            authors_df["authorEmail"].astype(str).str.strip().ne("").sum()
        )
        filled_count = 0

        def fill_email(row: pd.Series) -> str:
            nonlocal filled_count
            current = _cell_str(row.get("authorEmail"))
            if current:
                return current
            try:
                article_num = int(row.get("article") or 0)
            except (TypeError, ValueError):
                return current
            if not (1 <= article_num <= len(ordered_id_jems)):
                return current
            id_jems = ordered_id_jems[article_num - 1]
            normalized_name = self._normalize_name(
                str(row.get("authorFirstName") or ""),
                str(row.get("authorMiddleName") or ""),
                str(row.get("authorLastName") or ""),
            )
            if not id_jems or not normalized_name:
                return current
            new_email = email_index.get((id_jems, normalized_name), "").strip()
            if new_email:
                filled_count += 1
                return new_email
            return current

        authors_df["authorEmail"] = authors_df.apply(fill_email, axis=1)
        total_after = (
            authors_df["authorEmail"].astype(str).str.strip().ne("").sum()
        )
        print(
            f"E-mails já preenchidos antes: {original_non_empty} | "
            f"Preenchidos pela LLM: {filled_count} | "
            f"Total com e-mail após preenchimento: {total_after}"
        )
        return authors_df

    def save_authors_emails_2018(self, authors_df: pd.DataFrame) -> None:
        """
        Save updated authors DataFrame to Autores_emails_2018.csv.

        Args:
            authors_df: DataFrame with updated authorEmail values.
        """
        if authors_df.empty:
            print("DataFrame de autores vazio. Nada foi salvo.")
            return

        # Preserve original column order if possible
        desired_order = [
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

        columns = [c for c in desired_order if c in authors_df.columns]
        other_columns = [c for c in authors_df.columns if c not in columns]
        final_df = authors_df[columns + other_columns].copy() if other_columns else authors_df[columns].copy()
        # Evitar gravar NaN no CSV (ficaria "nan" no arquivo)
        final_df = final_df.fillna("")

        output_path = os.path.join(self.csv_folder, "Autores_emails_2018.csv")
        final_df.to_csv(output_path, sep=";", index=False)

        print(f"Arquivo salvo em: {output_path}")

