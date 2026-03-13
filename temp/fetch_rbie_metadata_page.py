"""
Script para inspecionar a página de metadados do RBIE 2018 e verificar
se há e-mail de autores no HTML. Rode a partir da raiz do projeto:

  conda run -n llms python temp/fetch_rbie_metadata_page.py

Salva o HTML em temp/metadata_sample_180.html e imprime trechos que
mencionam "Autor" ou "mail"/"email".
"""
import os
import sys
from pathlib import Path

# project root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from bs4 import BeautifulSoup
import requests  # type: ignore

from src.config.config_loader import ConfigLoader


def main():
    config = ConfigLoader("config/config.json")
    site_url = config.get_config_value("site_url")
    # site_url = "http://milanesa.ime.usp.br/rbie/index.php/sbie/issue/view/180"

    print("Baixando página do issue...", site_url)
    try:
        r = requests.get(site_url, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print("Erro ao baixar issue:", e)
        return

    soup = BeautifulSoup(r.content, "html.parser")
    sections = soup.find_all("h4", class_="tocSectionTitle")
    if not sections:
        print("Nenhuma seção encontrada (tocSectionTitle).")
        return

    # Primeiro artigo com link PDF
    metadados_url = None
    for section in sections:
        next_sib = section.find_next_sibling()
        while next_sib and next_sib.name == "table":
            pdf_link = next_sib.find("a", href=True, string="PDF")
            if pdf_link:
                pdf_url = pdf_link["href"]
                metadados_url = pdf_url.replace("article/view", "rt/metadata")
                break
            next_sib = next_sib.find_next_sibling()
        if metadados_url:
            break

    if not metadados_url:
        print("Nenhum link PDF encontrado.")
        return

    print("URL de metadados (primeiro artigo):", metadados_url)
    print("Baixando página de metadados...")
    try:
        r2 = requests.get(metadados_url, timeout=60)
        r2.raise_for_status()
    except Exception as e:
        print("Erro ao baixar metadados:", e)
        return

    html = r2.text
    out_path = ROOT / "temp" / "metadata_sample_180.html"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML salvo em:", out_path)

    # Trechos com Autor ou email
    soup2 = BeautifulSoup(html, "html.parser")
    for tag in soup2.find_all(["td", "th", "label", "span"]):
        t = (tag.get_text() or "").strip()
        if not t:
            continue
        if "utor" in t.lower() or "mail" in t.lower() or "e-mail" in t.lower():
            # Mostrar contexto: tag e irmãos
            parent = tag.parent
            if parent:
                row = parent.get_text(separator=" | ", strip=True)
                print("\n---")
                print("Texto do elemento:", t[:80])
                print("Linha (tr):", row[:200] if len(row) > 200 else row)


if __name__ == "__main__":
    main()
