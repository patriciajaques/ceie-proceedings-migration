"""
Debug: testa detecção da seção Referências no PDF 5760 com normalização.
"""
import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.utils.pdf_processor import PDFProcessor
from src.services.article_extractor import ArticleExtractor

# Need a minimal extractor just to use the method (no AI)
class _MinimalConfig:
    def get_config_value(self, key, default=None):
        return default

pdfs_dir = ROOT / "output" / "2018" / "pdfs"
pdf_path = pdfs_dir / "5760.pdf"
if not pdf_path.exists():
    print("PDF 5760 não encontrado")
    sys.exit(1)

proc = PDFProcessor(str(pdfs_dir))
text_pages, num_pages = proc.extract_text_from_each_page(str(pdf_path))
n = len(text_pages)
one_article_text = {"text_pages": text_pages, "numPages": n, "base_filename": "5760"}

# Dummy extractor (we only need get_reference_pages_text and _normalize)
from src.adapters.ai_client_interface import AIClientInterface
from src.config.config_loader import ConfigLoader
config = ConfigLoader(str(ROOT / "config" / "config.json"))
# Build minimal extractor - we need references_ai_client etc for init but we only call get_reference_pages_text
# Actually we can just call the static method and the strategy logic manually
extractor = ArticleExtractor(None, None, None, extraction_cache_path=None)  # type: ignore

# Test section strategy
section_text = extractor.get_reference_pages_text(one_article_text, strategy="section")
print(f"Strategy 'section' retornou: {len(section_text)} caracteres")
if section_text:
    print(f"Preview: {section_text[:400]}...")
else:
    print("Section retornou vazio - verificando primeiros 500 chars de cada página (normalizados):")
    for offset in range(min(5, n)):
        i = n - 1 - offset
        page = text_pages[i]
        region = extractor._normalize_page_for_heading_match(page)[:500]
        for h in ["referencias", "referencia", "references"]:
            if h in region:
                print(f"  Página {i+1}: contém '{h}' nos primeiros 500 chars")
                break
