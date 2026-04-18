import os
import json
import subprocess
import shutil
from typing import List, Tuple

import fitz

from src.utils.text_processor import TextProcessor


class PDFProcessor:
    """
    A class for processing PDF files. Processing here means extracting text from PDF files in a directory.
    """

    def __init__(self, directory):
        """
        Initialize the PDFProcessor class.

        Args:
            directory (str): The directory where the PDF files are located.
        """
        self.directory = directory

    def _extract_page_text_with_pymupdf(self, page: "fitz.Page") -> str:
        """
        Extract text from a single page using a TextPage with text flags.

        Using TextPage with TEXTFLAGS_TEXT can improve glyph-to-Unicode
        mapping in some PDFs compared to the plain page.get_text() call.
        """
        try:
            textpage = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
            return textpage.extractTEXT()
        except Exception:
            # Fallback to the default behavior if something goes wrong
            return page.get_text()

    def _is_text_suspect(self, text_pages: List[str]) -> bool:
        """
        Heuristic to decide if the extracted text likely has encoding problems.

        Reuses TextProcessor's encoding error patterns and considers the ratio
        of suspicious patterns in the whole document text.
        """
        if not text_pages:
            return False

        full_text = " ".join(text_pages)
        if not full_text.strip():
            return False

        # Use the same regex patterns defined in TextProcessor
        encoder = TextProcessor()
        regex = encoder._ENCODING_ERROR_REGEX  # type: ignore[attr-defined]

        matches = list(regex.finditer(full_text))
        if not matches:
            return False

        # Simple ratio: suspicious patterns per 1k characters
        text_len = max(len(full_text), 1)
        ratio_per_1k = (len(matches) * 1000.0) / text_len

        # Threshold chosen empiricamente: alguns ruídos são aceitáveis;
        # acima de ~2 ocorrências por 1k caracteres é um forte sinal.
        return ratio_per_1k >= 2.0

    def _extract_text_with_pdftotext(self, pdf_path: str) -> Tuple[List[str], int]:
        """
        Extract text from a PDF using the external `pdftotext` command (Poppler).

        Returns a list of page texts and the total number of pages, trying to
        preserve the same interface used by the PyMuPDF-based extractor.
        """
        if not shutil.which("pdftotext"):
            # pdftotext not available; caller should gracefully fall back
            return [], 0

        # Use UTF-8 encoding and layout preservation; output to stdout ("-").
        cmd = ["pdftotext", "-enc", "UTF-8", "-layout", pdf_path, "-"]
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return [], 0

        output = result.stdout
        if not output:
            return [], 0

        # pdftotext separates pages using form-feed characters ('\f').
        pages = output.split("\f")

        # Remove trailing empty segments and strip whitespace per page
        cleaned_pages: List[str] = [p.strip() for p in pages if p.strip()]

        total_pages = len(cleaned_pages)
        return cleaned_pages, total_pages

    def extract_text_from_each_page(self, pdf_path: str) -> Tuple[List[str], int]:
        """
        Extract text from each page of a PDF file using PyMuPDF (fitz).

        Args:
            pdf_path (str): The full path of the PDF file.

        Returns:
            tuple: A tuple containing a list of texts, where each position in the list contains the text of a page
                  of the PDF, and the total number of pages in the PDF.
        """
        doc = fitz.open(pdf_path)
        text_pages: List[str] = []

        try:
            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_text = self._extract_page_text_with_pymupdf(page)
                text_pages.append(page_text)
        finally:
            doc.close()

        # Remove empty pages at the end (if any)
        while text_pages and text_pages[-1].strip() == "":
            text_pages = text_pages[:-1]

        # If the PyMuPDF extraction looks suspicious, try pdftotext as a fallback
        if self._is_text_suspect(text_pages):
            alt_pages, alt_total = self._extract_text_with_pdftotext(pdf_path)
            if alt_pages and not self._is_text_suspect(alt_pages):
                text_pages = alt_pages
                total_pages = alt_total
            else:
                total_pages = len(text_pages)
        else:
            total_pages = len(text_pages)

        return text_pages, total_pages

    def process_pdf_at_path(
        self,
        pdf_path: str,
        number_of_pages_to_process: int,
    ) -> dict:
        """
        Extract text from a single PDF file.
        """
        text_pages, num_pages = self.extract_text_from_each_page(pdf_path)
        original_num_pages = num_pages
        if number_of_pages_to_process != -1 and number_of_pages_to_process > 0:
            text_pages = text_pages[:number_of_pages_to_process]
            num_pages = min(original_num_pages, number_of_pages_to_process)
        base_filename = os.path.splitext(os.path.basename(pdf_path))[0]
        return {
            "text_pages": text_pages,
            "numPages": num_pages,
            "base_filename": base_filename,
        }
