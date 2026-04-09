"""
Script de verificação: compara título, autores, resumo, idJEMS e pages
dos CSVs (Artigos.csv, Autores.csv) com os dados atuais do Milanesa.

Uso (a partir da raiz do projeto):
  conda run -n llms python src/tools/verify_csv_vs_milanesa.py

Parâmetros: definidos como variáveis no bloco if __name__ == "__main__".
Gera em temp/:
  - verificacao_csv_vs_milanesa_OK_YYYYMMDD_HHMMSS.csv (tudo que está certo)
  - verificacao_csv_vs_milanesa_DIVERGE_YYYYMMDD_HHMMSS.csv (apenas o que diverge ou está ausente no Milanesa)
E um resumo no terminal.
"""
import os
import sys
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

# Project root (must be set before local imports; script lives in src/tools/)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.config.config_loader import ConfigLoader  # noqa: E402
from src.services.anais_ojs_html_parser import OJSHTMLParser  # noqa: E402


def _norm(s: str) -> str:
    """Normaliza string para comparação: strip e espaços colapsados."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    return " ".join(s.split())


def _norm_name_for_compare(name: str) -> str:
    """Normaliza nome para comparação: minúsculas, sem acentos, espaços colapsados."""
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).strip().lower()
    s = " ".join(s.split())
    # Remove accents (NFD and drop combining characters)
    nfd = unicodedata.normalize("NFD", s)
    s = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return s


def _author_names_equivalent(csv_names: list[str], milanesa_names: list[str]) -> bool:
    """
    Considera listas de autores equivalentes se mesma quantidade e, para cada posição,
    os nomes são iguais após normalização (acentos, espaços) ou muito próximos (typos).
    """
    if len(csv_names) != len(milanesa_names):
        return False
    for c, m in zip(csv_names, milanesa_names):
        nc = _norm_name_for_compare(c)
        nm = _norm_name_for_compare(m)
        if nc == nm:
            continue
        # Allow small typos (e.g. João vs Jorão, André vs Andre): ratio >= 0.88
        if nc and nm and SequenceMatcher(None, nc, nm).ratio() >= 0.88:
            continue
        return False
    return True


def _similar_text(a: str, b: str, threshold: float) -> bool:
    """
    Returns True if two texts are similar enough, based on a normalized
    SequenceMatcher ratio. Used for abstracts where the LLM may have done
    small grammar/wording fixes but kept the overall content.
    """
    na = _norm(a).lower()
    nb = _norm(b).lower()
    if not na and not nb:
        return True
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold

def _authors_from_csv(authors_df: pd.DataFrame, seq: str) -> list[str]:
    """Lista de nomes completos dos autores do artigo (ordem) a partir de Autores.csv."""
    rows = authors_df[authors_df["article"].astype(str) == str(seq)]
    names = []
    for _, r in rows.sort_values("order").iterrows():
        parts = [
            r.get("authorFirstName", ""),
            r.get("authorMiddleName", ""),
            r.get("authorLastName", ""),
        ]
        name = " ".join(str(p).strip() for p in parts if pd.notna(p) and str(p).strip())
        names.append(name)
    return names


def _authors_from_milanesa(milanesa_item: dict) -> list[str]:
    """Lista de nomes completos dos autores a partir do item retornado pelo parser."""
    authors = milanesa_item.get("authors") or []
    names = []
    for a in authors:
        fn = a.get("authorFirstName", "") or ""
        mn = a.get("authorMiddleName", "") or ""
        ln = a.get("authorLastName", "") or ""
        name = " ".join(x.strip() for x in [fn, mn, ln] if x.strip())
        names.append(name)
    return names


def _first_page_from_pages(pages_str: str) -> str:
    """
    Extrai a primeira página do campo pages do CSV.
    O CSV tem formato 'primeira-última' (ex: '1-10', '11-20'); o Milanesa só fornece firstPage.
    Por isso a verificação de pages compara apenas: valor antes do traço (CSV) == firstPage (Milanesa).
    """
    if not pages_str or pd.isna(pages_str):
        return ""
    s = str(pages_str).strip()
    # Aceita hífen ou traço (en-dash, em-dash)
    for sep in ("-", "\u2013", "\u2014"):
        if sep in s:
            return s.split(sep)[0].strip()
    return s


def load_csv_data(csv_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carrega Artigos.csv e Autores.csv."""
    artigos_path = csv_dir / "Artigos.csv"
    autores_path = csv_dir / "Autores.csv"
    if not artigos_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {artigos_path}")
    if not autores_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {autores_path}")
    artigos = pd.read_csv(artigos_path, delimiter=";")
    autores = pd.read_csv(autores_path, delimiter=";")
    return artigos, autores


def fetch_milanesa_data(site_url: str, max_articles: int | None) -> list[dict]:
    """Obtém dados do Milanesa via OJSHTMLParser."""
    parser = OJSHTMLParser(site_url)
    num = -1 if max_articles is None else max_articles
    return parser.extract_articles_info_from_the_website(num_files_to_process=num)


def build_milanesa_by_id(milanesa_list: list[dict]) -> dict[str, dict]:
    """Mapa idJEMS -> item do Milanesa (com titleOrig do metadata quando houver)."""
    by_id = {}
    for item in milanesa_list:
        id_jems = str(item.get("idJEMS", "")).strip()
        if not id_jems:
            continue
        # Título: preferir o da página de metadados (titleOrig2) se existir
        title_meta = item.get("titleOrig2") or item.get("titleOrig") or ""
        item_copy = dict(item)
        item_copy["_title_compare"] = _norm(title_meta) or _norm(item.get("titleOrig", ""))
        by_id[id_jems] = item_copy
    return by_id


def run_comparison(
    artigos_df: pd.DataFrame,
    autores_df: pd.DataFrame,
    milanesa_by_id: dict[str, dict],
    similarity_threshold: float,
) -> list[dict]:
    """Compara cada artigo do CSV com o Milanesa. Retorna lista de linhas do relatório."""
    rows = []
    for _, art in artigos_df.iterrows():
        seq = art.get("seq", "")
        id_jems = str(art.get("idJEMS", "")).strip()
        if not id_jems:
            continue
        milanesa = milanesa_by_id.get(id_jems)
        if not milanesa:
            rows.append({
                "idJEMS": id_jems,
                "seq": seq,
                "campo": "idJEMS",
                "status": "AUSENTE_MILANESA",
                "valor_csv": id_jems,
                "valor_milanesa": "",
            })
            continue

        csv_title = _norm(art.get("titleOrig", ""))
        mil_title = milanesa.get("_title_compare", "")
        if csv_title != mil_title:
            rows.append({
                "idJEMS": id_jems,
                "seq": seq,
                "campo": "titleOrig",
                "status": "DIVERGE",
                "valor_csv": csv_title[:200] + ("..." if len(csv_title) > 200 else ""),
                "valor_milanesa": mil_title[:200] + ("..." if len(mil_title) > 200 else ""),
            })
        else:
            rows.append({
                "idJEMS": id_jems,
                "seq": seq,
                "campo": "titleOrig",
                "status": "OK",
                "valor_csv": "",
                "valor_milanesa": "",
            })

        csv_authors = _authors_from_csv(autores_df, seq)
        mil_authors = _authors_from_milanesa(milanesa)
        auth_ok = _author_names_equivalent(csv_authors, mil_authors)
        rows.append({
            "idJEMS": id_jems,
            "seq": seq,
            "campo": "autores",
            "status": "OK" if auth_ok else "DIVERGE",
            "valor_csv": " | ".join(csv_authors[:5]) + (" ..." if len(csv_authors) > 5 else ""),
            "valor_milanesa": " | ".join(mil_authors[:5]) + (" ..." if len(mil_authors) > 5 else ""),
        })

        csv_abs_raw = art.get("abstractOrig", "") or ""
        mil_abs_raw = milanesa.get("abstractOrig", "") or ""
        csv_abs = _norm(csv_abs_raw)
        mil_abs = _norm(mil_abs_raw)
        abs_ok = csv_abs == mil_abs or _similar_text(
            csv_abs,
            mil_abs,
            threshold=similarity_threshold,
        )
        rows.append({
            "idJEMS": id_jems,
            "seq": seq,
            "campo": "abstractOrig",
            "status": "OK" if abs_ok else "DIVERGE",
            # Para facilitar auditoria, quando diverge gravamos o texto completo
            "valor_csv": "" if abs_ok else csv_abs_raw,
            "valor_milanesa": "" if abs_ok else mil_abs_raw,
        })

        csv_abs_en_raw = art.get("abstractEn", "") or ""
        mil_abs_en_raw = milanesa.get("abstractEn", "") or ""
        csv_abs_en = _norm(csv_abs_en_raw)
        mil_abs_en = _norm(mil_abs_en_raw)
        abs_en_ok = csv_abs_en == mil_abs_en or _similar_text(
            csv_abs_en,
            mil_abs_en,
            threshold=similarity_threshold,
        )
        rows.append({
            "idJEMS": id_jems,
            "seq": seq,
            "campo": "abstractEn",
            "status": "OK" if abs_en_ok else "DIVERGE",
            "valor_csv": "" if abs_en_ok else csv_abs_en_raw,
            "valor_milanesa": "" if abs_en_ok else mil_abs_en_raw,
        })

        # Milanesa só tem firstPage; o CSV tem "primeira-última". Verificamos só se a primeira coincide.
        csv_pages = str(art.get("pages", "")).strip()
        mil_first = str(milanesa.get("firstPage", "")).strip()
        csv_first = _first_page_from_pages(csv_pages)
        pages_ok = csv_first == mil_first
        rows.append({
            "idJEMS": id_jems,
            "seq": seq,
            "campo": "pages",
            "status": "OK" if pages_ok else "DIVERGE",
            "valor_csv": csv_pages,
            "valor_milanesa": f"firstPage={mil_first}",
        })

    return rows


def main(
    max_articles: int | None = None,
    year: str | None = None,
    similarity_threshold: float = 0.8,
) -> None:
    config = ConfigLoader("config/config.json")
    site_url = config.get_config_value("site_url")
    year = year or config.get_config_value("year", "2018")
    output_dir = config.get_config_value("output_dir", "output/")
    csv_dir = Path(output_dir) / str(year) / "csv"

    print("Carregando CSVs de", csv_dir)
    artigos_df, autores_df = load_csv_data(csv_dir)
    print("Buscando dados no Milanesa (isso pode demorar)...")
    milanesa_list = fetch_milanesa_data(site_url, max_articles)
    milanesa_by_id = build_milanesa_by_id(milanesa_list)

    report_rows = run_comparison(
        artigos_df,
        autores_df,
        milanesa_by_id,
        similarity_threshold=similarity_threshold,
    )
    report_df = pd.DataFrame(report_rows)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_dir = ROOT / "temp"

    df_ok = report_df[report_df["status"] == "OK"]
    df_diverge = report_df[report_df["status"].isin(["DIVERGE", "AUSENTE_MILANESA"])]

    path_ok = temp_dir / f"verificacao_csv_vs_milanesa_OK_{timestamp}.csv"
    path_diverge = temp_dir / f"verificacao_csv_vs_milanesa_DIVERGE_{timestamp}.csv"

    df_ok.to_csv(path_ok, sep=";", index=False)
    df_diverge.to_csv(path_diverge, sep=";", index=False)

    print("Arquivo com tudo que está OK:", path_ok)
    print("Arquivo apenas com o que diverge (ou ausente no Milanesa):", path_diverge)

    # Resumo
    total = report_df.shape[0]
    ok = (report_df["status"] == "OK").sum()
    diverge = (report_df["status"] == "DIVERGE").sum()
    ausente = (report_df["status"] == "AUSENTE_MILANESA").sum()
    artigos_verificados = report_df[report_df["status"] != "AUSENTE_MILANESA"]["idJEMS"].nunique()
    print("\n--- Resumo ---")
    print(f"Artigos com dados no Milanesa (verificados): {len(milanesa_by_id)}")
    print(f"Comparações efetuadas (campos x artigos): {artigos_verificados * 5}")
    print(f"OK: {ok}")
    print(f"DIVERGE: {diverge}")
    print(f"Artigos só no CSV (sem dado no Milanesa): {ausente}")
    if diverge > 0:
        print("\nDivergências por campo:")
        print(report_df[report_df["status"] == "DIVERGE"].groupby("campo").size())


if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    # Parâmetros: altere aqui para rodar o script
    MAX_ARTICLES = 5  # None = todos; ex.: 5 para testar só os 5 primeiros
    YEAR = None  # None = usa o ano do config; ex.: "2018" ou "2019"
    SIMILARITY_THRESHOLD = 0.8  # limiar para considerar resumos/abstracts semelhantes

    main(
        max_articles=MAX_ARTICLES,
        year=YEAR,
        similarity_threshold=SIMILARITY_THRESHOLD,
    )
