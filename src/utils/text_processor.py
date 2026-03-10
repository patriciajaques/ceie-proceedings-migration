# src/utils/text_processor.py (refactored)
import re
from src.adapters.ai_client_interface import AIClientInterface
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

        if self.detect_encoding_errors(text):
            return self.process_with_ai(text)

        # Basic text cleaning
        text = self.basic_cleaning(text)
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

    def detect_encoding_errors(self, text):
        """Detects common encoding errors in the text.

        Args:
            text (str): Text to be checked.

        Returns:
            bool: True if encoding errors are detected, False otherwise.
        """
        if not text:
            return False

        # Check if the text contains any of the patterns using the compiled regular expression
        return bool(self._ENCODING_ERROR_REGEX.search(text))

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
        corrected_text = self.ai_client.create_completion(instruction, False)
        if not corrected_text:
            print(
                "Error processing text with AI. "
                "(Correção de encoding falhou; usando limpeza básica. "
                "Pode ser limite de tokens, erro de rede ou resposta vazia.)"
            )
            return self.basic_cleaning(text)

        return corrected_text
