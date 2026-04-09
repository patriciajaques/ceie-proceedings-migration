"""
Script especial: artigo 112 (idJEMS=5760) tem DUAS seções "Referências".
Usar apenas a PENÚLTIMA ocorrência (a última é da tabela/apêndice).

- Extrai texto do PDF 5760.pdf
- Encontra todas as páginas que têm título "Referências"/"References" (início de linha)
- Usa a PENÚLTIMA dessas páginas e envia até 5 páginas a partir dela para a LLM
- Substitui as linhas do artigo 112 em Referencias.csv (com backup)

Executar na raiz do projeto:
  conda run -n llms python temp/fix_referencias_article_112_penultimate_section.py
"""
import csv
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_for_heading(text: str) -> str:
    """Normalize page text for section heading match (encoding/accents).
    Handles 'refer^encias' / 'referˆencias' (broken ê) so it matches 'referencias'.
    """
    if not text:
        return ""
    t = text.lower()
    # ê often appears as ^ or ˆ when encoding breaks (refer^encias, referˆencias)
    t = t.replace("^", "e")           # ASCII caret
    t = t.replace("\u02c6", "e")      # MODIFIER LETTER CIRCUMFLEX ACCENT (ˆ)
    t = t.replace("ˆ", "e")           # circumflex variant
    t = t.replace("\u02da", "o")
    t = t.replace("\u00b4", "")
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


HEADINGS_NORM = [
    _normalize_for_heading(h)
    for h in (
        "referências",
        "referencias",
        "referência",
        "references",
        "bibliography",
        "bibliografia",
    )
]
TITLE_REGION_LEN = 1200
MAX_PAGES_BLOCK = 5


def _page_has_section_title(page_text: str) -> bool:
    """True if page has section title: at line start, or after number, or as word in first region."""
    if not page_text or not page_text.strip():
        return False
    page_norm = _normalize_for_heading(page_text)
    region = page_norm[:TITLE_REGION_LEN]
    # 1) Line-based: line starts with heading (optional leading digits like "7. ")
    for line in region.split("\n"):
        line = line.strip()
        while line and line[0:1].isdigit():
            line = line.lstrip("0123456789.").strip()
        if not line:
            continue
        for h in HEADINGS_NORM:
            if line.startswith(h) or line == h or line.startswith(h + " "):
                return True
    # 2) Regex: (start or newline) + optional spaces/digits + heading
    for h in HEADINGS_NORM:
        if re.search(r"(^|\n)\s*[\d.]*\s*" + re.escape(h) + r"(?:\s|$|[:\s])", region):
            return True
    # 3) Fallback: heading appears as word in first 600 chars (section header often near top)
    for h in HEADINGS_NORM:
        if len(h) >= 6 and h in region[:600]:
            return True
    return False


def _indices_with_references_section(text_pages: list[str]) -> list[int]:
    """Return list of page indices (0-based) that have the references section title."""
    return [i for i, p in enumerate(text_pages) if _page_has_section_title(p)]


def _sanitize_cell(value) -> str:
    s = str(value).strip() if value is not None and not (isinstance(value, float) and pd.isna(value)) else ""
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    import os
    os.chdir(ROOT)

    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ROOT / ".env")

    from src.config.config_loader import ConfigLoader
    from src.adapters.langchain_client import LangChainClient
    from src.services.article_extractor import ArticleExtractor
    from src.utils.text_processor import TextProcessor
    from src.utils.pdf_processor import PDFProcessor

    config_loader = ConfigLoader(str(ROOT / "config" / "config.json"))
    year = str(config_loader.get_config_value("year", "2018"))
    output_dir = Path(config_loader.get_config_value("output_dir", "output"))
    csv_dir = output_dir / year / "csv"
    pdfs_dir = output_dir / year / "pdfs"

    seq_article = "112"
    id_jems = "5760"
    pdf_path = pdfs_dir / f"{id_jems}.pdf"
    refs_path = csv_dir / "Referencias.csv"

    if not pdf_path.exists():
        print(f"PDF não encontrado: {pdf_path}")
        sys.exit(1)
    if not refs_path.exists():
        print(f"Referencias.csv não encontrado: {refs_path}")
        sys.exit(1)

    # Extract pages
    pdf_processor = PDFProcessor(str(pdfs_dir))
    text_pages, n = pdf_processor.extract_text_from_each_page(str(pdf_path))
    indices = _indices_with_references_section(text_pages)

    if len(indices) >= 2:
        # Penultimate = second from the end
        start_idx = indices[-2]
        print(
            f"Encontradas {len(indices)} seções 'Referências'. "
            f"Usando penúltima: página índice {start_idx} (1-based: {start_idx + 1})."
        )
    elif len(indices) == 1:
        start_idx = indices[0]
        print(
            f"Encontrada 1 seção 'Referências'. Usando: página índice {start_idx} "
            f"(1-based: {start_idx + 1})."
        )
    else:
        # Fallback: last 3 pages (references usually at end)
        start_idx = max(0, len(text_pages) - 3)
        print(
            f"Nenhuma seção 'Referências' detectada. Fallback: últimas páginas "
            f"a partir do índice {start_idx} (1-based: {start_idx + 1})."
        )

    block = text_pages[start_idx : min(start_idx + MAX_PAGES_BLOCK, len(text_pages))]
    text_for_llm = "\n\n".join(block)
    print(f"Bloco: {len(block)} página(s).")

    # LLM
    ai_clients = {
        k: LangChainClient(config_loader, pk)
        for k, pk in [
            ("article_ai_client", "article_extraction"),
            ("references_ai_client", "references_extraction"),
            ("field_completion_ai_client", "field_completion"),
            ("text_processing_client", "text_processing"),
        ]
    }
    text_processor = TextProcessor(ai_clients["text_processing_client"])
    article_extractor = ArticleExtractor(
        ai_clients["article_ai_client"],
        ai_clients["references_ai_client"],
        ai_clients["field_completion_ai_client"],
        text_processor,
        extraction_cache_path=None,
    )
    text_for_llm = text_processor.clean_text(text_for_llm)
    refs_dict = article_extractor.extract_references_metadata_with_ai(text_for_llm)
    refs_list = refs_dict.get("references") or []
    print(f"LLM retornou {len(refs_list)} referência(s).")

    if not refs_list:
        print("Nenhuma referência extraída. Referencias.csv não foi alterado.")
        return

    # Build new rows for article 112
    headers_refs = ["article", "description", "doi", "link", "accessed", "order"]
    new_rows = []
    for order, ref in enumerate(refs_list, start=1):
        if isinstance(ref, dict):
            new_rows.append({
                "article": seq_article,
                "description": _sanitize_cell(ref.get("description", "")),
                "doi": _sanitize_cell(ref.get("doi", "")),
                "link": _sanitize_cell(ref.get("link", "")),
                "accessed": _sanitize_cell(ref.get("accessed", "")),
                "order": order,
            })
        else:
            new_rows.append({
                "article": seq_article,
                "description": _sanitize_cell(str(ref)),
                "doi": "",
                "link": "",
                "accessed": "",
                "order": order,
            })

    # Load CSV, remove old rows for article 112, append new, backup, save
    refs_df = pd.read_csv(refs_path, delimiter=";")
    refs_df["article"] = refs_df["article"].astype(str).str.strip()
    other = refs_df[refs_df["article"] != seq_article].copy()
    new_df = pd.DataFrame(new_rows, columns=headers_refs)
    combined = pd.concat([other, new_df], ignore_index=True)
    combined["_article_num"] = pd.to_numeric(combined["article"], errors="coerce").fillna(0)
    combined = combined.sort_values(by=["_article_num", "order"]).drop(columns=["_article_num"])

    backup_dir = csv_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"Referencias_backup_article112_penultimate_{timestamp}.csv"
    refs_df.to_csv(backup_path, sep=";", index=False, quoting=csv.QUOTE_ALL)
    print(f"Backup salvo: {backup_path}")

    combined.to_csv(refs_path, sep=";", index=False, quoting=csv.QUOTE_ALL)
    print(f"Referencias.csv atualizado: artigo {seq_article} com {len(new_rows)} referência(s) (penúltima seção).")


if __name__ == "__main__":
    main()
