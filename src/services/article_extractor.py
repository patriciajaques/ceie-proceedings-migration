import json
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from src.utils.text_processor import TextProcessor
from src.utils.section_abbrev import is_editorial_section_abbrev
from src.domain.article import Article, normalize_keywords_field
from src.adapters.ai_client_interface import AIClientInterface
from src.logging.json_logger import JsonLogger

# Reminder when appending PDF text to field-completion instructions (system prompt
# in prompts.yaml already describes full proceedings layout).
_PDF_FIELD_COMPLETION_STRUCTURE_HINT = (
    "Estrutura típica do excerto: título → autores → afiliações e e-mails → "
    "Resumo e/ou Abstract → depois secções numeradas (ex.: 1. Introdução), "
    "palavras-chave e rodapé dos anais (Anais do..., ISSN). "
    "Copie em abstractOrig/abstractEn somente o texto do Resumo ou do Abstract; "
    "não inclua autores, afiliações, corpo do artigo, introdução numerada, "
    "palavras-chave nem rodapé.\n\n"
)

# Keys sent to field-completion LLM (no references — avoids huge JSON and parse errors).
_FIELD_COMPLETION_LLM_PAYLOAD_KEYS: Tuple[str, ...] = (
    "idJEMS",
    "id_jems",
    "seq",
    "sectionAbbrev",
    "titleOrig",
    "titleEn",
    "abstractOrig",
    "abstractEn",
    "keywordsOrig",
    "keywordsEn",
    "language",
    "firstPage",
    "pages",
    "doi",
    "numPages",
    "authors",
)

# Expected JSON keys in the model reply (references omitted on purpose).
_FIELD_COMPLETION_RESPONSE_KEYS_HINT = (
    "Responda APENAS com um objeto JSON contendo estas chaves (omitir chaves que "
    "não alterar, exceto as que o enunciado pede para preencher): idJEMS, seq, "
    "sectionAbbrev, titleOrig, titleEn, abstractOrig, abstractEn, keywordsOrig, "
    "keywordsEn, language, firstPage, pages, doi, numPages, authors. "
    "NÃO inclua a chave \"references\". Use carateres UTF-8 literais nas strings "
    "(acentos normais); NÃO use escapes \\uXXXX. "
    "Se incluir \"authors\", repita os mesmos dados da entrada sem alterar nomes."
)

# Re-run field-completion LLM when metadata is still incomplete after merge (max per article).
_FIELD_COMPLETION_MAX_LLM_ATTEMPTS = 3


class ArticleExtractor:
    """Extracts metadata from articles based on text content.

    This class uses an AI client to extract structured information
    from academic articles based on text extracted from PDFs.
    """

    def __init__(
        self,
        references_ai_client: AIClientInterface,
        field_completion_ai_client: AIClientInterface,
        text_processor: Optional[TextProcessor] = None,
    ):
        """Initializes the article extractor.

        Args:
            references_ai_client (AIClientInterface): AI client for reference extraction.
            field_completion_ai_client (AIClientInterface): AI client for completing missing fields.
            text_processor (TextProcessor, optional): Text processor for cleaning text.
                If not provided, a new one will be created.
        """
        self.references_ai_client = references_ai_client
        self.field_completion_ai_client = field_completion_ai_client
        self.text_processor = text_processor or TextProcessor()

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
    def _field_completion_llm_payload(article_dict: Dict) -> Dict:
        """
        Subset of article metadata for field-completion LLM: no references list.

        Keeps authors for context; merge always restores authors from prior.
        """
        return {
            k: article_dict[k]
            for k in _FIELD_COMPLETION_LLM_PAYLOAD_KEYS
            if k in article_dict
        }

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
        t = t.replace("\u02c6", "e")  # MODIFIER LETTER CIRCUMFLEX (e.g. Referˆencia)
        t = t.replace("\u02da", "o")  # ring above
        t = t.replace("\u00b4", "")  # acute accent (often before letter)
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
                    block = text_pages[i : min(i + max_pages, n)]
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
        text_pages = one_article_text.get("text_pages") or []
        if not text_pages:
            return ""

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

    def extract_references_metadata_with_ai(self, last_pages: str) -> Dict:
        """Extracts references using AI.

        Args:
            last_pages (str): Text from the last pages of the article.

        Returns:
            dict: Dictionary with extracted references.
        """
        return self.extract_info_with_ai(self.references_ai_client, last_pages)

    @staticmethod
    def _nonempty_metadata_text(value: object) -> bool:
        """
        True if a metadata field counts as filled (cache/JSON may use str or list).
        """
        if value is None:
            return False
        if isinstance(value, list):
            return any(str(x).strip() for x in value if x is not None)
        if isinstance(value, dict):
            return False
        return bool(str(value).strip())

    def _needs_pdf_text_for_completion(self, article_dict: Dict) -> bool:
        """Verifica se o artigo não tem resumo/abstract e se a IA precisaria do texto do PDF."""
        abstract_orig = article_dict.get("abstractOrig")
        abstract_en = article_dict.get("abstractEn")
        return not self._nonempty_metadata_text(
            abstract_orig
        ) and not self._nonempty_metadata_text(abstract_en)

    def _needs_pdf_text_for_missing_abstract_en_only(self, article_dict: Dict) -> bool:
        """
        True when the site provided a Portuguese abstract but English is empty.

        In that case the PDF often still contains an English Abstract section; the
        LLM should prefer extracting it before translating abstractOrig.
        """
        abstract_orig = article_dict.get("abstractOrig")
        abstract_en = article_dict.get("abstractEn")
        return self._nonempty_metadata_text(
            abstract_orig
        ) and not self._nonempty_metadata_text(abstract_en)

    @staticmethod
    def _pdf_snippet_prioritize_english_abstract(
        pdf_text: str, max_total: int = 22000
    ) -> str:
        """
        Prefer a window around the English Abstract heading so it is not lost
        when a fixed head truncation omits that section.
        """
        t = (pdf_text or "").strip()
        if not t:
            return ""
        if len(t) <= max_total:
            return t
        m = re.search(r"(?im)(?:^|\n)\s*Abstract\s*[\.:\s\-]?", t)
        if not m:
            m = re.search(r"(?im)\bAbstract\b", t)
        if m:
            start = max(0, m.start() - 800)
            return t[start : start + max_total]
        return t[:max_total]

    def metadata_text_fields_complete(self, article_dict: Dict) -> bool:
        """
        True when title/abstract/keywords/language are filled enough to skip
        field-completion LLM and reuse ``articles_metadata_apos`` cache.

        Ignores structural fields (pages, doi, firstPage, numPages, etc.): those
        may be empty without invalidating a previously completed record.
        """
        d = article_dict
        nmt = self._nonempty_metadata_text
        sec = d.get("sectionAbbrev") or d.get("section_abbrev") or ""
        if is_editorial_section_abbrev(sec):
            return bool(
                nmt(d.get("titleOrig"))
                and nmt(d.get("titleEn"))
                and nmt(d.get("language"))
            )
        required = (
            "titleOrig",
            "titleEn",
            "abstractOrig",
            "abstractEn",
            "keywordsOrig",
            "keywordsEn",
            "language",
        )
        return all(nmt(d.get(k)) for k in required)

    # Words / patterns typical of Portuguese proceedings titles without accents
    # (e.g. "Capa dos Anais", "Contra-capa") so they are not mistaken for English.
    _PT_TITLE_TOKENS: frozenset[str] = frozenset(
        {
            "anais",
            "apresentacao",
            "apresentação",
            "capa",
            "comites",
            "comitês",
            "comunicacao",
            "comunicação",
            "das",
            "dos",
            "edicao",
            "edição",
            "prefacio",
            "prefácio",
            "sumario",
            "sumário",
        }
    )

    @staticmethod
    def _title_likely_portuguese_without_accents(title: str) -> bool:
        """
        True when the title is probably Portuguese but uses only ASCII letters
        (no accented chars). Those titles must not be treated as English by
        :meth:`_title_looks_english`, or ``titleEn`` would be skipped.
        """
        if not (title or "").strip():
            return False
        normalized = title.lower().replace("-", " ")
        tokens = re.findall(r"[a-záàâãéêíóôõúç]+", normalized)
        if any(t in ArticleExtractor._PT_TITLE_TOKENS for t in tokens):
            return True
        if "contra" in tokens and "capa" in tokens:
            return True
        return False

    @staticmethod
    def _title_looks_english(title: str) -> bool:
        """
        Heuristic: editorial titles already in English need no translation.

        Portuguese (accented or common unaccented words) implies not English-only.
        """
        if not (title or "").strip():
            return False
        if ArticleExtractor._title_likely_portuguese_without_accents(title):
            return False
        if any(c in title for c in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇñÑ¿¡"):
            return False
        letters = [c for c in title if c.isalpha()]
        if not letters:
            return False
        ascii_letters = sum(1 for c in letters if c.isascii())
        if ascii_letters / len(letters) < 0.9:
            return False
        # Reject if it looks like a page range or header line
        if re.fullmatch(r"[\d\s\-–—]+", title.strip()):
            return False
        return True

    def _field_complete_editorial(self, article_dict: Dict) -> Dict:
        """
        Editorials were excluded from generic field completion; fill titleEn and
        language without PDF context (avoids page numbers mistaken for titles).

        Abstracts and keywords are cleared — not expected for this document type.
        """
        out = dict(article_dict)
        title_orig = (out.get("titleOrig") or "").strip()
        title_en = (out.get("titleEn") or "").strip()
        language = (out.get("language") or "").strip().lower()

        if title_orig and title_en and language[:2] in ("pt", "en", "es"):
            for k in ("abstractOrig", "abstractEn", "keywordsOrig", "keywordsEn"):
                out[k] = ""
            return out

        need_title_en = not title_en
        need_language = not language or language[:2] not in ("pt", "en", "es")

        if title_orig and need_title_en and self._title_looks_english(title_orig):
            out["titleEn"] = title_orig
            out["language"] = "en"
        elif title_orig and need_title_en:
            minimal = {
                "titleOrig": title_orig,
                "titleEn": "",
                "language": "pt",
            }
            instruction = (
                json.dumps(minimal, ensure_ascii=False)
                + "\n\nThis metadata row is an EDITORIAL (not a full research paper). "
                "Return ONLY one JSON object with exactly these string keys: "
                "titleOrig, titleEn, language. "
                "Keep titleOrig exactly as given. "
                "Set titleEn to a faithful English translation of titleOrig; "
                "if titleOrig is already English, set titleEn to the same text. "
                "Never put page numbers, page ranges, or journal headers in titleEn. "
                'Set language to "en", "pt", or "es" matching the primary '
                "language of titleOrig."
            )
            new_d = self.extract_info_with_ai(
                self.field_completion_ai_client, instruction
            )
            if new_d and isinstance(new_d, dict):
                te = (new_d.get("titleEn") or "").strip()
                if te:
                    out["titleEn"] = te
                lang = (new_d.get("language") or "").strip().lower()
                if lang[:2] in ("pt", "en", "es"):
                    out["language"] = lang[:2]
        elif title_orig and need_language:
            out["language"] = "en" if self._title_looks_english(title_orig) else "pt"

        lang_after = (out.get("language") or "").strip().lower()
        if title_orig and (not lang_after or lang_after[:2] not in ("pt", "en", "es")):
            out["language"] = "en" if self._title_looks_english(title_orig) else "pt"

        for k in ("abstractOrig", "abstractEn", "keywordsOrig", "keywordsEn"):
            out[k] = ""
        return out

    @staticmethod
    def _normalize_abstract_from_llm(text: str, role: str) -> str:
        """
        Trim LLM-filled abstract fields: drop section labels and tail pasted from PDF.

        ``role`` is \"en\" (abstractEn) or \"orig\" (abstractOrig). Cuts introduction
        headings even when glued to the abstract on the same line (e.g. ``...end. 1.
        Introdução``).
        """
        t = (text or "").strip()
        if not t:
            return ""

        def _cut_at(pattern: str, s: str) -> str:
            m = re.search(pattern, s)
            return s[: m.start()].strip() if m else s

        if role == "en":
            t = re.sub(r"(?i)^abstract\s*[.:–—\-]?\s*", "", t, count=1)
            lines = t.split("\n")
            if lines and re.match(
                r"(?i)^abstract\s*[.:–—\-]?\s*$", lines[0].strip()
            ):
                t = "\n".join(lines[1:]).strip()
            t = _cut_at(r"(?i)\bResumo\s*[.:]", t)
        else:
            t = re.sub(r"(?i)^resumo\s*[.:–—\-]?\s*", "", t, count=1)
            lines = t.split("\n")
            if lines and re.match(
                r"(?i)^resumo\s*[.:–—\-]?\s*$", lines[0].strip()
            ):
                t = "\n".join(lines[1:]).strip()
            t = _cut_at(r"(?im)(?:^|\n)\s*abstract\s*[\.:\s\-]?", t)

        t = _cut_at(
            r"(?i)(?:^|\n)\s*(?:\d+\s*[.)]\s*)?(?:Introdução|Introduction)\b",
            t,
        )
        t = _cut_at(
            r"(?i)(?<=[.!?])\s+(?:\d+\s*[.)]\s*)(?:Introdução|Introduction)\b",
            t,
        )
        t = _cut_at(
            r"(?i)(?:^|\n)\s*(?:Palavras[\s-]*chave|Keywords?|Key\s+words)\b",
            t,
        )
        t = _cut_at(
            r"(?i)(?<=[.!?])\s+(?:Palavras[\s-]*chave|Keywords?|Key\s+words)\b",
            t,
        )
        t = _cut_at(r"(?i)(?:^|\n)\s*Anais do\b", t)
        t = _cut_at(r"(?i)(?<=[.!?])\s+Anais do\b", t)
        t = _cut_at(r"\n_{4,}", t)
        t = _cut_at(r"\n={5,}", t)
        return t.strip()

    @staticmethod
    def _merge_field_completion_dict(prior: Dict, llm: Dict) -> Dict:
        """
        Overlay LLM JSON on the dict built before field completion.

        Title, authors, pagination, references, and a valid ``language`` from the
        site must stay as loaded from the Milanesa site (TOC + rt/metadata) and
        enrich; the LLM only fills gaps like titleEn and abstracts when the site
        did not provide them.

        Keys used only for LLM self-explanation (e.g. ``fieldFailureReasons`` from
        prompts.yaml) are dropped here so they never reach ``Article`` or saved JSON;
        the raw model response remains in ``ai_calls.log.jsonl``.
        """
        llm = dict(llm)
        llm.pop("fieldFailureReasons", None)
        out = {**prior, **llm}
        _from_site_and_enrich = (
            "titleOrig",
            "authors",
            "firstPage",
            "pages",
            "numPages",
            "references",
            "doi",
            "idJEMS",
            "seq",
            "sectionAbbrev",
        )
        for key in _from_site_and_enrich:
            if key in prior:
                out[key] = prior[key]
        # Website language (OJS metadata) wins when valid; LLM fills gaps only.
        prior_lang = (prior.get("language") or "").strip().lower()
        if prior_lang[:2] in ("pt", "en", "es"):
            out["language"] = prior_lang[:2]
        # Do not wipe filled text fields when the model returns empty strings.
        for key in (
            "abstractOrig",
            "abstractEn",
            "keywordsOrig",
            "keywordsEn",
            "titleEn",
        ):
            llm_val = llm.get(key)
            prior_val = prior.get(key)
            if (
                llm_val is not None
                and str(llm_val).strip() == ""
                and str(prior_val or "").strip()
            ):
                out[key] = prior_val
        ao_merge = out.get("abstractOrig")
        if ao_merge is not None and str(ao_merge).strip():
            out["abstractOrig"] = ArticleExtractor._normalize_abstract_from_llm(
                str(ao_merge), "orig"
            )
        ae = out.get("abstractEn")
        if ae is not None and str(ae).strip():
            out["abstractEn"] = ArticleExtractor._normalize_abstract_from_llm(
                str(ae), "en"
            )
        for _kw in ("keywordsOrig", "keywordsEn"):
            if _kw in out:
                out[_kw] = normalize_keywords_field(out.get(_kw))
        return out

    def _build_field_completion_instruction(
        self,
        article_dict_for_payload: Dict,
        id_jems: str,
        pdf_raw_by_id: Dict[str, str],
    ) -> str:
        """
        Build the user instruction for one field-completion LLM call.

        ``article_dict_for_payload`` is the current metadata shown to the model
        (after prior merges on retry); site/enrich merge still uses the original
        dict passed to :meth:`_merge_field_completion_dict`.
        """
        llm_payload = self._field_completion_llm_payload(article_dict_for_payload)
        instruction = json.dumps(llm_payload, ensure_ascii=False)
        if self._needs_pdf_text_for_completion(
            llm_payload
        ) and pdf_raw_by_id.get(id_jems):
            raw_text = pdf_raw_by_id[id_jems]
            pdf_text = self.text_processor.clean_text(raw_text)
            pdf_snippet = self._pdf_snippet_prioritize_english_abstract(pdf_text)
            instruction = (
                instruction
                + "\n\n[Os campos de resumo (abstractOrig, abstractEn) estão vazios. "
                "Use o texto das primeiras páginas do artigo abaixo para extrair ou redigir "
                "um resumo em português e em inglês e, a partir dele, preencher as palavras-chave "
                "(keywordsOrig e keywordsEn).]\n\n"
                + _PDF_FIELD_COMPLETION_STRUCTURE_HINT
                + "--- Texto das primeiras páginas do artigo ---\n\n"
                + pdf_snippet
                + "\n\n--- Fim do texto ---\n\n"
                "IMPORTANTE: "
                + _FIELD_COMPLETION_RESPONSE_KEYS_HINT
                + " Sua resposta deve ser EXCLUSIVAMENTE esse JSON, sem texto do artigo "
                "nem explicações antes ou depois."
            )
            print(
                "  (incluído texto do PDF para extração de resumo e palavras-chave)",
                flush=True,
            )
        elif self._needs_pdf_text_for_missing_abstract_en_only(
            llm_payload
        ) and pdf_raw_by_id.get(id_jems):
            raw_text = pdf_raw_by_id[id_jems]
            pdf_text = self.text_processor.clean_text(raw_text)
            pdf_snippet = self._pdf_snippet_prioritize_english_abstract(pdf_text)
            instruction = (
                instruction
                + "\n\n[O campo abstractEn está vazio, mas abstractOrig já contém o resumo "
                "em português (metadado do site). PRIORIDADE: no trecho abaixo, copie "
                "literalmente o texto da secção em inglês (Abstract / ABSTRACT), sem "
                "traduzir o resumo em português. Só se não existir nenhuma secção em "
                "inglês nesse trecho, traduza abstractOrig para inglês em abstractEn. "
                "Não altere abstractOrig. Preencha os demais campos ainda vazios.]\n\n"
                + _PDF_FIELD_COMPLETION_STRUCTURE_HINT
                + "--- Texto das primeiras páginas do artigo ---\n\n"
                + pdf_snippet
                + "\n\n--- Fim do texto ---\n\n"
                "IMPORTANTE: "
                + _FIELD_COMPLETION_RESPONSE_KEYS_HINT
                + " Sua resposta deve ser EXCLUSIVAMENTE esse JSON, sem texto do artigo "
                "nem explicações antes ou depois."
            )
            print(
                "  (incluído texto do PDF para abstract em inglês ou tradução do resumo)",
                flush=True,
            )
        else:
            instruction = (
                instruction
                + "\n\n"
                + _FIELD_COMPLETION_RESPONSE_KEYS_HINT
                + " Retorne APENAS esse JSON, sem texto antes ou depois."
            )
        return instruction

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

        Quando só há resumo em PT no site (abstractOrig preenchido, abstractEn vazio) e há
        PDF em pdf_raw_by_id, o texto das primeiras páginas é incluído para a IA obter o
        abstract em inglês do próprio PDF quando existir; caso contrário, traduzir abstractOrig.

        Se após o merge ainda faltarem campos de texto obrigatórios, a mesma rotina de
        field completion é repetida até _FIELD_COMPLETION_MAX_LLM_ATTEMPTS vezes,
        usando o dicionário fundido como base do JSON enviado à IA (o merge continua a
        ancorar títulos/autores/referências no dicionário original do site).

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
                # Reuse apos JSON only when text metadata is complete (not "any key empty").
                if self.metadata_text_fields_complete(cached_dict):
                    updated_articles.append(Article.from_dict(cached_dict))
                    continue

            # Convert to dictionary for AI compatibility
            article_dict = article.to_dict()

            if is_editorial_section_abbrev(article_dict.get("sectionAbbrev")):
                merged = self._field_complete_editorial(article_dict)
                updated_articles.append(Article.from_dict(merged))
                continue

            if (
                article_dict.get("titleOrig") or article_dict.get("titleEn")
            ) and not self.metadata_text_fields_complete(article_dict):

                print(
                    f"Improving article record with seq "
                    f"{article_dict.get('seq')} and idJEMS: "
                    f"{article_dict.get('idJEMS')}",
                    flush=True,
                )

                merged: Optional[Dict] = None
                prior_site = article_dict

                for attempt in range(_FIELD_COMPLETION_MAX_LLM_ATTEMPTS):
                    base = merged if merged is not None else prior_site
                    if self.metadata_text_fields_complete(base):
                        break

                    if attempt > 0:
                        print(
                            f"  (field completion: nova tentativa {attempt + 1}/"
                            f"{_FIELD_COMPLETION_MAX_LLM_ATTEMPTS} — ainda há campos "
                            "de texto obrigatórios vazios)",
                            flush=True,
                        )

                    instruction = self._build_field_completion_instruction(
                        base, id_jems, pdf_raw_by_id
                    )
                    new_dict = self.extract_info_with_ai(
                        self.field_completion_ai_client, instruction
                    )
                    if new_dict and isinstance(new_dict, dict):
                        merged = self._merge_field_completion_dict(
                            prior_site, new_dict
                        )

                if merged is not None:
                    updated_articles.append(Article.from_dict(merged))
                else:
                    updated_articles.append(article)
            else:
                updated_articles.append(article)

        return updated_articles

    def has_empty_fields(self, dictionary: Dict) -> bool:
        """True when text metadata still needs field completion (inverse of complete)."""
        return not self.metadata_text_fields_complete(dictionary)

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

            print(
                "**** Failed after 3 attempts. Returning empty dictionary. ****",
                flush=True,
            )
            return {}

    def _log_ai_call(
        self, ai_client: AIClientInterface, instruction: str, response: str
    ) -> None:
        """
        Registra em arquivo o prompt enviado à IA e a resposta bruta recebida.

        Inclui o campo "step" com o prompt_key do cliente (ex.: field_completion,
        references_extraction) para identificar a etapa no log e no LangSmith.
        """
        step = getattr(ai_client, "prompt_key", "unknown")
        system_message = getattr(ai_client, "system_message", None)
        response_metadata = None
        if hasattr(ai_client, "last_response_metadata"):
            response_metadata = getattr(ai_client, "last_response_metadata", None)

        JsonLogger.log_ai_call(
            step=step,
            instruction=instruction,
            response=response,
            system_message=system_message,
            response_metadata=response_metadata,
        )

    def _extract_json_from_text(self, text: str) -> str:
        """Extrai um bloco JSON de texto que pode conter conteúdo antes/depois."""
        if not text or not text.strip():
            raise ValueError("Resposta vazia")
        text = text.strip()
        # 1) Se existir bloco ```json ... ```, usar só o conteúdo entre as marcas
        if "```" in text:
            parts = text.split("```")
            for part in parts:
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
