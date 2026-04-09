import json
import os
import unicodedata
from typing import Dict, List, Optional
from src.utils.text_processor import TextProcessor
from src.domain.article import Article
from src.adapters.ai_client_interface import AIClientInterface
from src.logging.json_logger import JsonLogger


class ArticleExtractor:
    """Extracts metadata from articles based on text content.

    This class uses an AI client to extract structured information
    from academic articles based on text extracted from PDFs.
    """

    def __init__(
        self,
        article_ai_client: AIClientInterface,
        references_ai_client: AIClientInterface,
        field_completion_ai_client: AIClientInterface,
        text_processor: Optional[TextProcessor] = None,
        extraction_cache_path: Optional[str] = None,
    ):
        """Initializes the article extractor.

        Args:
            article_ai_client (AIClientInterface): AI client for article metadata extraction.
            references_ai_client (AIClientInterface): AI client for reference extraction.
            field_completion_ai_client (AIClientInterface): AI client for completing missing fields.
            text_processor (TextProcessor, optional): Text processor for cleaning text.
                If not provided, a new one will be created.
            extraction_cache_path (str, optional): Path to JSON file for incremental extraction cache.
                If provided, articles already extracted will be loaded from cache and skipped.
        """
        self.article_ai_client = article_ai_client
        self.references_ai_client = references_ai_client
        self.field_completion_ai_client = field_completion_ai_client
        self.text_processor = text_processor or TextProcessor()
        self.extraction_cache_path = extraction_cache_path

    def _load_extraction_cache(self) -> Dict[str, dict]:
        """Carrega o cache de extração do disco, se existir."""
        if not self.extraction_cache_path or not os.path.exists(self.extraction_cache_path):
            return {}
        try:
            with open(self.extraction_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            if isinstance(data, dict):
                return data
            return {}
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_extraction_cache(self, cache: Dict[str, dict]) -> None:
        """Persiste o cache de extração no disco."""
        if not self.extraction_cache_path:
            return
        os.makedirs(os.path.dirname(self.extraction_cache_path), exist_ok=True)
        with open(self.extraction_cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    def extract_articles_data_from_PDF_text(
        self, all_files_text: List[Dict]
    ) -> List[Article]:
        """Extracts article data from PDF text.

        Not used by the main Migrator flow (site-first migration builds article
        metadata from the OJS website and uses PDF text only for references
        and page counts). Kept for tooling or manual experiments.

        Usa cache incremental: artigos já extraídos são carregados do disco e pulados.
        O cache é salvo após cada artigo para permitir retomada em caso de interrupção.
        O cache não é reduzido quando se roda com menos arquivos: mantém todos os artigos
        já processados para recuperação e retomada.

        Args:
            all_files_text (list): List of dictionaries containing text extracted from PDFs.

        Returns:
            list: List of Article objects with article metadata.
        """
        articles_list = []
        cache = self._load_extraction_cache() if self.extraction_cache_path else {}

        for count, one_article_text in enumerate(all_files_text, start=1):
            base_filename = one_article_text["base_filename"]
            if base_filename in cache:
                articles_list.append(Article.from_dict(cache[base_filename]))
                print(f"\n\nProcessed article number {count} (from cache)\n")
                continue

            article = self.extract_article_data(one_article_text)
            articles_list.append(article)
            cache[base_filename] = article.to_dict()
            if self.extraction_cache_path:
                self._save_extraction_cache(cache)
            print(f"\n\nProcessed article number {count}\n")

        return articles_list

    def extract_article_data(self, one_article_text: Dict) -> Article:
        """Extracts data from a single article.

        Args:
            one_article_text (dict): Dictionary containing text extracted from a PDF.

        Returns:
            Article: Article object with article metadata.
        """
        first_pages = self.extract_pages(one_article_text, page_location="first")
        first_pages = self.text_processor.clean_text(first_pages)

        # Prefer section "Referências"/"References" (from end backward); else last 3 pages
        section_pages_raw = self.get_reference_pages_text(
            one_article_text, strategy="section"
        )
        if section_pages_raw:
            last_pages = section_pages_raw
        else:
            last_pages = self.get_reference_pages_text(
                one_article_text, strategy="last"
            )
        last_pages = self.text_processor.clean_text(last_pages)

        # Check if we have section information
        section_abbrev = one_article_text.get("sectionAbbrev", None)

        article_dict = self.extract_metadata_with_ai(
            first_pages, last_pages, section_abbrev
        )

        # Fallback: if we used "last" and got few refs, try section (e.g. encoding)
        if section_abbrev != "EDT" and not section_pages_raw:
            refs = article_dict.get("references") or []
            if len(refs) < 2:
                section_pages = self.get_reference_pages_text(
                    one_article_text, strategy="section"
                )
                if section_pages:
                    section_pages = self.text_processor.clean_text(
                        section_pages
                    )
                    refs_fallback = (
                        self.extract_references_metadata_with_ai(section_pages)
                    )
                    refs_fallback_list = refs_fallback.get(
                        "references", []
                    )
                    if len(refs_fallback_list) > len(refs):
                        article_dict["references"] = refs_fallback_list

        # Update with additional information
        article_dict["num_pages"] = one_article_text["numPages"]
        article_dict["id_jems"] = one_article_text["base_filename"]

        # Language:
        # - Preferir o valor retornado pelo modelo em article_dict["language"]
        # - Se o modelo não informar a língua, assumir "pt" como padrão
        if not article_dict.get("language"):
            article_dict["language"] = "pt"

        # Convert to Article object
        return Article.from_dict(article_dict)

    # Headings used to detect the references section when last pages are appendices
    REFERENCE_SECTION_HEADINGS = (
        "referências",
        "referencias",
        "referência",
        "references",
        "bibliography",
        "bibliografia",
    )

    # Maximum number of pages sent to the LLM for reference extraction (never exceed)
    MAX_PAGES_FOR_REFERENCES = 5

    @staticmethod
    def _normalize_page_for_heading_match(text: str) -> str:
        """Normalize page text so section headings are found despite encoding issues.

        PDFs often have broken encoding (e.g. 'Referˆencia' instead of 'Referência').
        Lowercase, replace common PDF glitches, then strip accents so that
        'referências' and 'referencia' both match.
        """
        if not text:
            return ""
        t = text.lower()
        # Common PDF encoding artifacts that replace accented letters
        t = t.replace("\u02c6", "e")   # MODIFIER LETTER CIRCUMFLEX (e.g. Referˆencia)
        t = t.replace("\u02da", "o")   # ring above
        t = t.replace("\u00b4", "")   # acute accent (often before letter)
        nfkd = unicodedata.normalize("NFKD", t)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    def get_reference_pages_text(
        self, one_article_text: Dict, strategy: str = "last"
    ) -> str:
        """Get text for reference extraction: last 3 pages or section block.

        Never returns more than MAX_PAGES_FOR_REFERENCES pages of text.

        Args:
            one_article_text: Dict with "text_pages" (list of page strings).
            strategy: "last" = last 3 pages (fallback); "section" = search
                backward from last page for "Referências"/"References" (última,
                penúltima, antepenúltima, etc., up to 4 pages before) and return
                up to MAX_PAGES_FOR_REFERENCES pages from that page (fallback
                when last pages are appendices).

        Returns:
            Concatenated page text, or empty string if strategy "section" and
            no heading found.
        """
        text_pages = one_article_text.get("text_pages") or []
        if not text_pages:
            return ""
        n = len(text_pages)
        max_pages = self.MAX_PAGES_FOR_REFERENCES

        if strategy == "last":
            # Use last 3 pages so we include the start of references (antepenultimate)
            # when refs span antepenultimate + penultimate + last; capped at max_pages
            take = min(3, max_pages, n)
            return "\n\n".join(text_pages[-take:])

        if strategy == "section":
            # Normalized headings for matching (PDFs often have broken encoding)
            norm_headings = [
                self._normalize_page_for_heading_match(h)
                for h in self.REFERENCE_SECTION_HEADINGS
            ]
            # Section titles are at start of a line (e.g. "Referências" or "6. Referências");
            # avoid matching "ID Referência" inside tables. Check first 800 chars line by line.
            title_region_len = 800

            def _page_has_section_title(pagenorm: str) -> bool:
                region = pagenorm[:title_region_len]
                for line in region.split("\n"):
                    line = line.strip()
                    # Skip empty; allow optional numbering like "6." or "7."
                    while line and line[0:1].isdigit():
                        line = line.lstrip("0123456789.")
                        line = line.strip()
                    if not line:
                        continue
                    for h in norm_headings:
                        if line.startswith(h) or line == h:
                            return True
                return False

            # Search backward: last page, then penultimate, then antepenultimate,
            # up to 4 pages before (so 5 attempts)
            for offset in range(min(max_pages, n)):
                i = n - 1 - offset
                if i < 0:
                    break
                page = text_pages[i]
                if not page:
                    continue
                page_norm = self._normalize_page_for_heading_match(page)
                if _page_has_section_title(page_norm):
                    block = text_pages[i: min(i + max_pages, n)]
                    return "\n\n".join(block)
            return ""

        return ""

    def extract_pages(self, one_article_text: Dict, page_location: str) -> str:
        """Extracts text from specified pages of an article.

        Args:
            one_article_text (dict): Dictionary containing text extracted from a PDF.
            page_location (str): Location of pages to extract ("first" or "last").

        Returns:
            str: Text from the specified pages.
        """
        text_pages = one_article_text["text_pages"]

        if page_location == "first":
            # Strategy for initial pages
            first_page = text_pages[0]

            if len(text_pages) < 2 or any(
                word in first_page.lower()
                for word in ["introducao", "introdução", "introduction"]
            ):
                return str(first_page)
            else:
                second_page = text_pages[1]
                return f"{first_page}, {second_page}"

        elif page_location == "last":
            # Strategy for final pages
            if len(text_pages) == 1:
                return str(text_pages[0])

            last_page = text_pages[-1]
            ref_indicators = [
                "references",
                "referências",
                "referencias",
                "bibliography",
                "bibliografia",
                "referência",
                "referˆencia",
            ]

            if len(text_pages) < 2 or any(
                word in last_page.lower() for word in ref_indicators
            ):
                return str(last_page)
            else:
                third_last_page = text_pages[-3] if len(text_pages) > 3 else ""
                second_last_page = text_pages[-2]
                return f"{third_last_page} {second_last_page} {last_page}"

        # Default behavior for invalid argument
        raise ValueError(f"Invalid page location: {page_location}")

    def extract_metadata_with_ai(
        self, first_pages: str, last_pages: str, section_abbrev: Optional[str] = None
    ) -> Dict:
        """Extracts metadata using AI.

        Args:
            first_pages (str): Text from the first pages of the article.
            last_pages (str): Text from the last pages of the article.
            section_abbrev (str, optional): Section abbreviation. Defaults to None.

        Returns:
            dict: Dictionary with article metadata and references.
        """
        article_dict = self.extract_article_metadata_with_ai(first_pages)
        article_dict["firstPages"] = first_pages
        article_dict["lastPages"] = last_pages

        # Adjust sectionAbbrev field if provided
        if section_abbrev:
            article_dict["sectionAbbrev"] = section_abbrev

        # Only extract references if NOT an editorial
        if section_abbrev != "EDT":
            references_dict = self.extract_references_metadata_with_ai(last_pages)
            article_dict["references"] = references_dict.get("references", [])
        else:
            # For editorials, just add an empty references list
            article_dict["references"] = []

        return article_dict

    def extract_article_metadata_with_ai(self, first_pages: str) -> Dict:
        """Extracts article metadata using AI.

        Args:
            first_pages (str): Text from the first pages of the article.

        Returns:
            dict: Dictionary with article metadata.
        """
        return self.extract_info_with_ai(self.article_ai_client, first_pages)

    def extract_references_metadata_with_ai(self, last_pages: str) -> Dict:
        """Extracts references using AI.

        Args:
            last_pages (str): Text from the last pages of the article.

        Returns:
            dict: Dictionary with extracted references.
        """
        return self.extract_info_with_ai(self.references_ai_client, last_pages)

    def _needs_pdf_text_for_completion(self, article_dict: Dict) -> bool:
        """Verifica se o artigo não tem resumo/abstract e se a IA precisaria do texto do PDF."""
        abstract_orig = (article_dict.get("abstractOrig") or "").strip()
        abstract_en = (article_dict.get("abstractEn") or "").strip()
        return not abstract_orig and not abstract_en

    def do_field_completion_of_missing_values_in_dic(
        self,
        articles_list: List[Article],
        completion_cache: Optional[Dict[str, dict]] = None,
        pdf_raw_by_id: Optional[Dict[str, str]] = None,
    ) -> List[Article]:
        """Completes missing fields in article metadata.

        Usa cache incremental: artigos já completados em execuções anteriores são
        reutilizados e não passam pela IA novamente.

        Quando o artigo não tem resumo (abstractOrig/abstractEn), e há texto bruto do PDF
        em pdf_raw_by_id, chama clean_text apenas para esse artigo e envia à IA para
        extrair resumo e palavras-chave (mesmo padrão da fase 1: corrige só quando vai usar).

        Args:
            articles_list (list): List of Article objects with metadata.
            completion_cache (dict, optional): Cache {idJEMS: article_dict} de execuções anteriores.
                Se fornecido e o artigo estiver no cache, usa o valor em cache e pula a IA.
            pdf_raw_by_id (dict, optional): Mapa id_jems -> texto bruto das primeiras páginas.
                clean_text é chamado só para o artigo que for completar, quando precisar do texto.

        Returns:
            list: Updated list of Article objects with completed fields.
        """
        updated_articles = []
        completion_cache = completion_cache or {}
        pdf_raw_by_id = pdf_raw_by_id or {}

        for article in articles_list:
            id_jems = article.id_jems or article.to_dict().get("idJEMS", "")
            if id_jems in completion_cache:
                cached_dict = completion_cache[id_jems]
                # Só reutiliza o cache se o registro já estiver completo.
                # Se ainda tiver campos vazios, deixa cair no fluxo normal
                # para tentar novamente chamar a IA em execuções futuras.
                if not self.has_empty_fields(cached_dict):
                    updated_articles.append(Article.from_dict(cached_dict))
                    continue

            # Convert to dictionary for AI compatibility
            article_dict = article.to_dict()

            if (
                (article_dict.get("titleOrig") or article_dict.get("titleEn"))
                and article_dict.get("sectionAbbrev") != "EDT"
                and self.has_empty_fields(article_dict)
            ):

                print(
                    f"Improving article record with seq "
                    f"{article_dict.get('seq')} and idJEMS: "
                    f"{article_dict.get('idJEMS')}",
                    flush=True,
                )

                # Remove fields that don't need to be sent to AI
                clean_dict = article_dict.copy()
                clean_dict.pop("firstPages", None)
                clean_dict.pop("lastPages", None)

                instruction = json.dumps(clean_dict)
                if self._needs_pdf_text_for_completion(clean_dict) and pdf_raw_by_id.get(id_jems):
                    # clean_text só para este artigo (igual à fase 1: corrige quando vai usar)
                    raw_text = pdf_raw_by_id[id_jems]
                    pdf_text = self.text_processor.clean_text(raw_text)
                    instruction = (
                        instruction
                        + "\n\n[Os campos de resumo (abstractOrig, abstractEn) estão vazios. "
                        "Use o texto das primeiras páginas do artigo abaixo para extrair ou redigir "
                        "um resumo em português e em inglês e, a partir dele, preencher as palavras-chave "
                        "(keywordsOrig e keywordsEn).]\n\n--- Texto das primeiras páginas do artigo ---\n\n"
                        + (pdf_text[:15000] if len(pdf_text) > 15000 else pdf_text)
                        + "\n\n--- Fim do texto ---\n\n"
                        "IMPORTANTE: Sua resposta deve ser EXCLUSIVAMENTE o dicionário JSON completo "
                        "(com todas as chaves: seq, titleOrig, titleEn, abstractOrig, abstractEn, keywordsOrig, "
                        "keywordsEn, etc.). Não inclua texto do artigo nem explicações antes ou depois do JSON."
                    )
                    print("  (incluído texto do PDF para extração de resumo e palavras-chave)", flush=True)
                else:
                    instruction = (
                        instruction
                        + "\n\nRetorne APENAS o dicionário JSON completo com os campos preenchidos, "
                        "sem nenhum texto antes ou depois."
                    )

                new_dict = self.extract_info_with_ai(
                    self.field_completion_ai_client, instruction
                )

                if new_dict and isinstance(new_dict, dict):
                    # Convert the updated dictionary back to an Article object
                    updated_article = Article.from_dict(new_dict)
                    updated_articles.append(updated_article)
                else:
                    updated_articles.append(article)
            else:
                updated_articles.append(article)

        return updated_articles

    def has_empty_fields(self, dictionary: Dict) -> bool:
        """Checks if the dictionary has empty fields.

        Args:
            dictionary (dict): Dictionary to check.

        Returns:
            bool: True if there are empty fields, False otherwise.
        """
        for key, value in dictionary.items():
            # Ignore specific fields and empty lists (which may be valid)
            if (
                key not in ["firstPages", "lastPages", "references"]
                and not value
                and value != 0
            ):
                return True
        return False

    def extract_info_with_ai(
        self, ai_client: AIClientInterface, instruction: str, recursion_count: int = 0
    ) -> Dict:
        """Extracts information using AI.

        Args:
            ai_client (AIClientInterface): AI client for extraction.
            instruction (str): Instruction for the AI.
            recursion_count (int): Recursion counter for limited retry attempts.

        Returns:
            dict: Dictionary with extracted information.
        """
        step = getattr(ai_client, "prompt_key", "unknown")
        print(f"  [LLM] Etapa: {step} ...", flush=True)
        json_info = ai_client.create_completion(instruction, True)

        # Log bruto da chamada à IA (com step explícito para depuração e LangSmith)
        self._log_ai_call(ai_client, instruction, json_info)

        try:
            return self.parse_ai_response(json_info)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"\n\n**** Error decoding JSON: {e} ****", flush=True)
            response_preview = json_info[:500] if json_info else "None"
            print(
                f"**** Response received from model (first 500 chars): "
                f"{response_preview} ****\n\n",
                flush=True,
            )

            # Try again with recursion limit
            if recursion_count < 3:
                return self.extract_info_with_ai(
                    ai_client, instruction, recursion_count + 1
                )

            print("**** Failed after 3 attempts. Returning empty dictionary. ****", flush=True)
            return {}

    def _log_ai_call(
        self, ai_client: AIClientInterface, instruction: str, response: str
    ) -> None:
        """
        Registra em arquivo o prompt enviado à IA e a resposta bruta recebida.

        Inclui o campo "step" com o prompt_key do cliente (ex.: field_completion,
        article_extraction) para identificar a etapa no log e no LangSmith.
        """
        step = getattr(ai_client, "prompt_key", "unknown")
        system_message = getattr(ai_client, "system_message", None)
        JsonLogger.log_ai_call(
            step=step,
            instruction=instruction,
            response=response,
            system_message=system_message,
        )

    def _extract_json_from_text(self, text: str) -> str:
        """Extrai um bloco JSON de texto que pode conter conteúdo antes/depois."""
        if not text or not text.strip():
            raise ValueError("Resposta vazia")
        text = text.strip()
        # 1) Se existir bloco ```json ... ```, usar só o conteúdo entre as marcas
        if "```" in text:
            parts = text.split("```")
            for j, part in enumerate(parts):
                if part.strip().lower().startswith("json"):
                    part = part.split("\n", 1)[-1] if "\n" in part else part[4:]
                    text = part.strip()
                    break
        # 2) Encontra o primeiro { e extrai o objeto por balanceamento de chaves
        start = text.find("{")
        if start == -1:
            raise ValueError("Nenhum objeto JSON encontrado na resposta")
        depth = 0
        for i, c in enumerate(text[start:], start=start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        raise ValueError("Objeto JSON incompleto (chaves não balanceadas)")

    def parse_ai_response(self, json_info: str) -> Dict:
        """Parses the AI response and extracts JSON.

        Args:
            json_info (str): AI response that should contain JSON.

        Returns:
            dict: Parsed JSON data.

        Raises:
            ValueError: If valid JSON cannot be found.
            json.JSONDecodeError: If the found JSON is not valid.
        """
        json_str = self._extract_json_from_text(json_info)
        return json.loads(json_str)
