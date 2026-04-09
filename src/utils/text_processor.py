# src/utils/text_processor.py (refactored)
import re
import unicodedata
from src.adapters.ai_client_interface import AIClientInterface
from src.logging.json_logger import JsonLogger
from typing import Optional, List, Pattern


class TextProcessor:
    """Utility for processing and cleaning text.

    This class provides methods for cleaning and processing
    text extracted from PDFs or other sources.
    """

    # Constant with common encoding error patterns
    ENCODING_ERROR_PATTERNS: List[str] = [
        "´ı",
        "c¸˜a",
        "´o",
        "´e",
        "˜a",
        "˜o",
        "¸c",
        "´a",
        "´i",
        "´u",
    ]

    # Compiled regex pattern for better performance
    _ENCODING_ERROR_REGEX: Pattern = re.compile(
        "|".join(re.escape(pattern) for pattern in ENCODING_ERROR_PATTERNS)
    )

    def __init__(self, ai_client: Optional[AIClientInterface] = None):
        """Initializes the text processor.

        Args:
            ai_client (AIClientInterface, optional): AI client for advanced
                text processing. Defaults to None.
        """
        self.ai_client = ai_client

    def clean_text(self, text):
        """Cleans the text, removing unwanted characters and normalizing.

        Args:
            text (str): Text to be cleaned.

        Returns:
            str: Cleaned text.
        """
        if not text:
            return ""

        # Primeiro aplica correções determinísticas conhecidas de encoding,
        # baseadas em padrões recorrentes observados nos textos dos PDFs.
        text = self.apply_known_encoding_fixes(text)

        # Depois disso, ainda verifica se sobraram padrões de encoding quebrado.
        # Só em caso afirmativo recorre à IA; caso contrário, faz limpeza básica.
        if self.detect_encoding_errors(text):
            return self.process_with_ai(text)

        # Basic text cleaning
        text = self.basic_cleaning(text)
        return text

    def apply_known_encoding_fixes(self, text: str) -> str:
        """
        Aplica correções determinísticas para sequências comuns de encoding quebrado.

        Em vez de corrigir palavras específicas (como \"Ciˆencia\"), a estratégia
        aqui é corrigir **padrões de acentuação** recorrentes, por exemplo:
        - \"´a\" -> \"á\", \"´e\" -> \"é\"
        - \"ˆa\" -> \"â\", \"ˆe\" -> \"ê\"
        - \"˜a\" -> \"ã\", \"˜o\" -> \"õ\"
        - \"¸c\" -> \"ç\"

        Além disso, alguns padrões compostos muito frequentes (como \"c¸˜a\")
        são tratados de forma especial, pois representam sequências como \"ção\".
        """
        if not text:
            return ""

        # 0) Ligaduras comuns em PDFs (fi, fl).
        text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")

        # 1) Substituições PRÉ-NFKC — feitas enquanto os diacríticos ainda estão
        #    na forma "espaçadora" (¸ U+00B8, ˜ U+02DC, ´ U+00B4, ˆ U+02C6).
        #
        #    IMPORTANTE: o NFKC decompõe esses caracteres em ESPAÇO + diacrítico
        #    combinante (ex.: ˜ → U+0020 + U+0303). Se as substituições forem feitas
        #    DEPOIS do NFKC, os padrões compostos como "c¸˜ao" já não existem mais na
        #    string — e o NFC acaba fixando o diacrítico na letra errada (ex.: ç̃a em
        #    vez de çã). Por isso, toda correção possível é feita ANTES do NFKC.
        #
        #    Ordem: padrões mais longos primeiro para evitar substituições parciais.
        pre_nfkc_replacements = [
            # Sequências c + cedilha + til (muito frequentes: ção, ções, çã, çõ)
            ("c¸˜ao",  "ção"),
            ("c¸˜oes", "ções"),
            ("c¸˜a",   "çã"),
            ("c¸˜o",   "çõ"),
            ("C¸˜A",   "ÇÃ"),
            ("C¸˜O",   "ÇÕ"),
            # Cedilha espaçadora sozinha
            ("¸c", "ç"),  ("¸C", "Ç"),
            # Til espaçador + vogal
            ("˜a", "ã"),  ("˜o", "õ"),  ("˜A", "Ã"),  ("˜O", "Õ"),
            # Acento agudo + dotless-i (U+0131): PDF codifica "í" como ´ + ı
            ("´ı", "í"),
            # Acento agudo + vogais normais
            ("´a", "á"),  ("´e", "é"),  ("´i", "í"),  ("´o", "ó"),  ("´u", "ú"),
            ("´A", "Á"),  ("´E", "É"),  ("´I", "Í"),  ("´O", "Ó"),  ("´U", "Ú"),
            # Acento circunflexo + vogais
            ("ˆa", "â"),  ("ˆe", "ê"),  ("ˆi", "î"),  ("ˆo", "ô"),  ("ˆu", "û"),
            ("ˆA", "Â"),  ("ˆE", "Ê"),  ("ˆI", "Î"),  ("ˆO", "Ô"),  ("ˆU", "Û"),
            # Crase
            ("`a", "à"),  ("`A", "À"),
        ]
        for wrong, correct in pre_nfkc_replacements:
            text = text.replace(wrong, correct)

        # 2) Normaliza NFKC. Após as substituições pré-NFKC, os padrões problemáticos
        #    (c¸˜, ´ı, etc.) já estão corrigidos, então o NFKC não vai mais introduzir
        #    espaços espúrios para esses casos.
        text = unicodedata.normalize("NFKC", text)

        # 3) Pode ainda haver espaços espúrios entre diacríticos combinantes gerados
        #    pelo NFKC em padrões não cobertos pelas substituições pré-NFKC. Remove
        #    esses espaços nas três combinações possíveis.
        combining_marks = r"[\u0300-\u036F]"
        # letra/dígito + espaço(s) + diacrítico combinante
        text = re.sub(rf"(\w)\s+({combining_marks})",              r"\1\2", text)
        # diacrítico combinante + espaço(s) + diacrítico combinante (ex.: ̧ ̃ → ̧̃)
        text = re.sub(rf"({combining_marks})\s+({combining_marks})", r"\1\2", text)
        # diacrítico combinante + espaço(s) + letra/dígito
        text = re.sub(rf"({combining_marks})\s+(\w)",              r"\1\2", text)

        # 4) Padrões genéricos de acentuação quebrada: mapeia o par (marcador, vogal)
        #    para o respectivo caractere acentuado.
        acute_map = {
            "a": "á",
            "e": "é",
            "i": "í",
            "o": "ó",
            "u": "ú",
            "A": "Á",
            "E": "É",
            "I": "Í",
            "O": "Ó",
            "U": "Ú",
        }
        circumflex_map = {
            "a": "â",
            "e": "ê",
            "i": "î",
            "o": "ô",
            "u": "û",
            "A": "Â",
            "E": "Ê",
            "I": "Î",
            "O": "Ô",
            "U": "Û",
        }
        tilde_map = {
            "a": "ã",
            "o": "õ",
            "A": "Ã",
            "O": "Õ",
        }
        cedilla_map = {
            "c": "ç",
            "C": "Ç",
        }

        # Substituições simples de dois caracteres, feitas de forma sequencial.
        # A ordem importa pouco aqui porque os marcadores (´, ˆ, ˜, ¸) são distintos.
        for marker, mapping in (
            ("´", acute_map),
            ("ˆ", circumflex_map),
            ("˜", tilde_map),
            ("¸", cedilla_map),
        ):
            for base, accented in mapping.items():
                text = text.replace(marker + base, accented)

        # Tratamento adicional: se ainda restarem combinações de vogal + qualquer
        # diacrítico "agudo" comum, aplica o mesmo mapeamento de forma genérica.
        # Inclui variações de acento que às vezes aparecem em PDFs.
        acute_like = "[\u00B4\u02CA\u0301\u2019']"  # ´, modifier acute, combining acute, alguns apóstrofos

        def _replace_acute_sequences(text_local: str, pattern_map: dict) -> str:
            for base, accented in pattern_map.items():
                # marcador antes da vogal
                text_local = re.sub(acute_like + base, accented, text_local)
                # vogal seguida do marcador
                text_local = re.sub(base + acute_like, accented, text_local)
            return text_local

        text = _replace_acute_sequences(
            text,
            {
                "a": "á",
                "e": "é",
                "i": "í",
                "o": "ó",
                "u": "ú",
                "A": "Á",
                "E": "É",
                "I": "Í",
                "O": "Ó",
                "U": "Ú",
            },
        )

        # Normaliza para NFC para garantir caracteres pré‑compostos.
        text = unicodedata.normalize("NFC", text)

        # Pós-NFC 1 — til combinante (U+0303) preso em consoante antes de a/o.
        #
        # Ocorre quando o NFKC introduziu ` ̃` e o passo 3 colapsou o espaço,
        # mas o NFC fixou o U+0303 na consoante anterior em vez de na vogal seguinte.
        # Ex.: ç̃a → çã,  ç̃o → çõ,  s̃ao → são,  ñao → não.
        #
        # Regra para a forma não-composta (U+0303 ainda visível como combining):
        text = re.sub(
            r"(.)\u0303([ao])",
            lambda m: m.group(1) + ("ã" if m.group(2) == "a" else "õ"),
            text,
        )
        # Regra para ñ (U+00F1) e Ñ (U+00D1) — formas pré-compostas do NFC;
        # ñ nunca ocorre em português, sempre indica til na vogal seguinte.
        text = (text
                .replace("ña", "nã").replace("ño", "nõ")
                .replace("Ña", "Nã").replace("Ño", "Nõ"))

        # Pós-NFC 2 — acento agudo preso em consoante antes de dotless-i (ı, U+0131).
        #
        # O PDF codifica "mínio" como "m´ı" (m + acento espaçador + dotless-i).
        # Após NFKC+NFC, m + combining-acute compõe ḿ (U+1E3F), deixando ı intocado.
        # Aqui detectamos qualquer {consoante-com-agudo}ı e transferimos o acento:
        # ḿı → mí,  ńı → ní,  ćı → cí,  śı → sí,  ĺı → lí, etc.
        def _fix_acute_on_consonant_before_dotless_i(t: str) -> str:
            result: list[str] = []
            i = 0
            while i < len(t):
                ch = t[i]
                if i + 1 < len(t) and t[i + 1] == "\u0131":  # ı (dotless-i) segue
                    nfd = unicodedata.normalize("NFD", ch)
                    if len(nfd) >= 2 and nfd[1] == "\u0301":  # tem acento agudo combinante
                        result.append(nfd[0])   # consoante base, sem acento
                        result.append("í")
                        i += 2
                        continue
                result.append(ch)
                i += 1
            return "".join(result)

        text = _fix_acute_on_consonant_before_dotless_i(text)

        # Pós-NFC 3 — hifens de quebra de linha (artefato de extração de PDF).
        #
        # Quando uma palavra é quebrada ao final de uma linha no PDF, o texto
        # extraído fica como "pala- vra" (hífen + espaço + continuação).
        # A LLM sempre une essas partes; aqui fazemos o mesmo deterministicamente.
        #
        # Regra: letra + "- " + letra-minúscula → junção direta (sem hífen).
        # Usar letra-minúscula no segundo grupo evita afetar compostos legítimos
        # onde a segunda parte começa com maiúscula (ex.: "Pan-Americano").
        # Compostos sem espaço (ex.: "bem-estar") não são afetados porque não
        # possuem espaço após o hífen.
        text = re.sub(
            r"([A-Za-zÀ-ÖØ-öø-ÿ])-\s+([a-zà-öø-ÿ])",
            r"\1\2",
            text,
        )

        return text

    def basic_cleaning(self, text):
        """Performs basic cleaning on the text.

        Args:
            text (str): Text to be cleaned.

        Returns:
            str: Cleaned text.
        """
        # Remove extra spaces
        text = re.sub(r"\s+", " ", text)
        # Remove control characters
        text = re.sub(r"[\x00-\x1F\x7F]", "", text)
        return text.strip()

    def detect_encoding_errors(self, text: str) -> bool:
        """Detects common encoding errors in the text.

        Em vez de acionar em qualquer ocorrência isolada dos padrões, esta função
        considera a **densidade** de erros por tamanho de texto, para evitar
        chamar a LLM em casos com apenas alguns ruídos marginais.

        Args:
            text (str): Text to be checked.

        Returns:
            bool: True if encoding errors are detected with relevant density,
                  False otherwise.
        """
        if not text:
            return False

        text = text.strip()
        if not text:
            return False

        matches = list(self._ENCODING_ERROR_REGEX.finditer(text))
        if not matches:
            return False

        # Densidade de padrões suspeitos por 1k caracteres
        text_len = max(len(text), 1)
        ratio_per_1k = (len(matches) * 1000.0) / text_len

        # Mesmo limiar usado em _is_text_suspect no PDFProcessor:
        # alguns ruídos são aceitáveis; acima de ~2 ocorrências por 1k caracteres
        # é um forte sinal de texto com problemas relevantes de encoding.
        return ratio_per_1k >= 2.0

    def process_with_ai(self, text):
        """Uses the AI client to process text with problems.

        Args:
            text (str): Text to be processed.

        Returns:
            str: Text processed by AI.
        """
        if not self.ai_client:
            # If there is no AI client, just do basic cleaning
            return self.basic_cleaning(text)

        # Prepare instruction for AI (adapted to the new interface)
        instruction = f"""Correct the following text with encoding errors.
            Maintain the original meaning, but fix words that have encoding errors.

            TEXT WITH ERROR:
            {text}
            """
        print("  [LLM] Etapa: text_processing (correção de encoding) ...", flush=True)
        corrected_text = self.ai_client.create_completion(instruction, False)
        # Log explícito: etapa text_processing (correção de encoding), não field_completion
        JsonLogger.log_ai_call(
            step="text_processing",
            instruction=instruction,
            response=corrected_text or "",
            system_message=getattr(self.ai_client, "system_message", None),
            response_metadata=getattr(
                self.ai_client, "last_response_metadata", None
            ),
        )
        if not corrected_text:
            print(
                "Error processing text with AI. "
                "(Correção de encoding falhou; usando limpeza básica. "
                "Pode ser limite de tokens, erro de rede ou resposta vazia.)"
            )
            return self.basic_cleaning(text)

        return corrected_text
