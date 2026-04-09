"""
Streamlit app: references from Referencias.csv (left) and PDF pages (right).

Right side: last N pages as images in a scrollable area; last 2 at the bottom,
scroll up to see previous pages. No header crop.
"""
import base64
import os
from pathlib import Path
import fitz
import pandas as pd
import streamlit as st

from src.config.config_loader import ConfigLoader


ROOT = Path(__file__).resolve().parents[2]


def _load_artigos_and_referencias(
    output_dir: Path, year: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Artigos.csv and Referencias.csv from output/{year}/csv."""
    csv_dir = output_dir / year / "csv"
    artigos_path = csv_dir / "Artigos.csv"
    refs_path = csv_dir / "Referencias.csv"

    if not artigos_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {artigos_path}")
    if not refs_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {refs_path}")

    artigos = pd.read_csv(artigos_path, delimiter=";")
    referencias = pd.read_csv(refs_path, delimiter=";")
    return artigos, referencias


def _references_for_article(
    refs_df: pd.DataFrame, seq: str
) -> list[dict]:
    """Get references for an article by matching Referencias.article == seq."""
    seq_str = str(seq).strip()
    rows = refs_df[refs_df["article"].astype(str).str.strip() == seq_str]
    refs: list[dict] = []
    for _, r in rows.sort_values("order").iterrows():
        refs.append(
            {
                "order": int(r.get("order", 0)) if pd.notna(r.get("order")) else 0,
                "description": _safe_str(r.get("description", "")),
                "doi": _safe_str(r.get("doi", "")),
                "link": _safe_str(r.get("link", "")),
                "accessed": _safe_str(r.get("accessed", "")),
            }
        )
    return refs


def _safe_str(val) -> str:
    """Return stripped string from CSV cell, empty if NaN."""
    if pd.isna(val):
        return ""
    return str(val or "").strip()


def _display_pdf_last_pages_scrollable(
    pdf_path: Path,
    num_pages: int = 8,
    scale: float = 1.0,
    scroll_height: int = 500,
) -> None:
    """Show last 2 pages side by side at top; previous pages in scrollable area below."""
    if not pdf_path.exists():
        st.warning("PDF não encontrado para este artigo.")
        return
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            st.warning("PDF sem páginas.")
            doc.close()
            return
        total = doc.page_count
        start_idx = max(0, total - num_pages)
        mat = fitz.Matrix(scale, scale)

        def img_html(i: int, png_b64: str) -> str:
            return (
                f'<span style="font-size:0.85em; color:#555;">Página {i + 1} de {total}</span><br>'
                f'<img src="data:image/png;base64,{png_b64}" style="width:100%; max-width:100%; display:block;" />'
            )

        # Last 2 pages: render and show side by side
        last_two = []
        for i in (total - 2, total - 1):
            if i < 0:
                continue
            page = doc[i]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            last_two.append((i, png_b64))

        # Previous pages (3rd last, 4th last, ...) for scrollable block
        scroll_parts = []
        for i in range(total - 3, start_idx - 1, -1):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            scroll_parts.append(
                f'<div style="margin-bottom:0.5em;">'
                f"{img_html(i, png_b64)}"
                f"</div>"
            )
        doc.close()

        # Top: 2 columns with last 2 pages side by side
        row_two = ""
        if len(last_two) >= 2:
            row_two = (
                '<div style="display:flex; gap:0.5em; margin-bottom:0.5em;">'
                f'<div style="flex:1;">{img_html(last_two[0][0], last_two[0][1])}</div>'
                f'<div style="flex:1;">{img_html(last_two[1][0], last_two[1][1])}</div>'
                "</div>"
            )
        elif len(last_two) == 1:
            row_two = f'<div style="margin-bottom:0.5em;">{img_html(last_two[0][0], last_two[0][1])}</div>'

        scroll_content = "".join(scroll_parts)
        scroll_div = (
            f'<div style="height:{scroll_height}px; overflow-y:auto; border:1px solid #ddd;">'
            f"{scroll_content}</div>"
        ) if scroll_parts else ""

        html = f'<div>{row_two}{scroll_div}</div>'
        st.markdown(html, unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"Erro ao abrir PDF: {e}")


def _build_articles_with_references(
    artigos_df: pd.DataFrame, refs_df: pd.DataFrame
) -> list[dict]:
    """Build list of articles with idJEMS, seq, title and list of references."""
    artigos_df = artigos_df.copy()
    artigos_df["seq"] = artigos_df["seq"].astype(str).str.strip()
    artigos_df["idJEMS"] = artigos_df["idJEMS"].astype(str).str.strip()
    refs_df = refs_df.copy()
    refs_df["article"] = refs_df["article"].astype(str).str.strip()

    articles: list[dict] = []
    for _, row in artigos_df.iterrows():
        seq = row["seq"]
        id_jems = row["idJEMS"]
        title = _safe_str(row.get("titleOrig", "")) or _safe_str(row.get("titleEn", ""))
        refs = _references_for_article(refs_df, seq)
        articles.append(
            {
                "seq": seq,
                "idJEMS": id_jems,
                "title": title or f"(seq={seq})",
                "references": refs,
            }
        )
    articles.sort(key=lambda x: int(x["seq"]) if str(x["seq"]).isdigit() else 0)
    return articles


def main() -> None:
    st.set_page_config(
        page_title="Referências do artigo × Última página do PDF",
        layout="wide",
    )
    # Compact paragraph spacing so reference list uses less vertical space
    st.markdown(
        "<style>.stMarkdown p { margin: 0.2em 0 !important; line-height: 1.35 !important; }</style>",
        unsafe_allow_html=True,
    )

    config = ConfigLoader("config/config.json")
    year = str(config.get_config_value("year", "2018"))
    output_dir = Path(config.get_config_value("output_dir", "output/"))

    try:
        artigos_df, refs_df = _load_artigos_and_referencias(output_dir, year)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    articles = _build_articles_with_references(artigos_df, refs_df)
    if not articles:
        st.info("Nenhum artigo encontrado.")
        return

    st.sidebar.markdown("### Dados")
    st.sidebar.write(f"Artigos: {len(articles)}")
    st.sidebar.write(f"Ano: {year}")

    seq_options = [a["seq"] for a in articles]

    if "idx" not in st.session_state:
        st.session_state["idx"] = 0

    current_idx_for_select = min(
        max(st.session_state["idx"], 0),
        len(seq_options) - 1,
    )
    selected_seq = st.sidebar.selectbox(
        "Ir para o artigo (seq)",
        options=seq_options,
        index=current_idx_for_select,
    )
    if selected_seq in seq_options:
        st.session_state["idx"] = seq_options.index(selected_seq)

    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
    with col_nav1:
        if st.button("Anterior", disabled=st.session_state["idx"] <= 0):
            st.session_state["idx"] = max(0, st.session_state["idx"] - 1)
    with col_nav3:
        if st.button(
            "Próximo",
            disabled=st.session_state["idx"] >= len(articles) - 1,
        ):
            st.session_state["idx"] = min(
                len(articles) - 1,
                st.session_state["idx"] + 1,
            )

    current_idx = st.session_state["idx"]
    current = articles[current_idx]

    with col_nav2:
        st.markdown(
            f"**Registro {current_idx + 1} de {len(articles)}** "
            f"(seq={current['seq']}, idJEMS={current['idJEMS']})"
        )

    left_col, right_col = st.columns(2)

    with left_col:
        refs = current["references"]
        if not refs:
            st.markdown("*Nenhuma referência cadastrada para este artigo.*")
        else:
            parts = []
            for ref in refs:
                order = ref.get("order", 0)
                desc = ref.get("description", "")
                doi = ref.get("doi", "")
                link = ref.get("link", "")
                accessed = ref.get("accessed", "")
                line = f"**{order}. ** {desc}"
                if doi:
                    line += f"  \nDOI: `{doi}`"
                if link:
                    line += f"  \n[Link]({link})"
                if accessed:
                    line += f"  \nAcesso: {accessed}"
                parts.append(line)
            # Single block, one line break between refs = compact (no "---" dividers)
            st.markdown("  \n  \n".join(parts))

    with right_col:
        st.subheader("Últimas páginas do PDF (2 últimas lado a lado; role para ver anteriores)")
        pdfs_dir = output_dir / year / "pdfs"
        pdf_path = pdfs_dir / f"{current['idJEMS']}.pdf"
        if not pdf_path.exists():
            st.warning(
                f"PDF não encontrado em {os.path.relpath(pdf_path, ROOT)}"
            )
        else:
            _display_pdf_last_pages_scrollable(
                pdf_path, num_pages=8, scale=1.0, scroll_height=700
            )


if __name__ == "__main__":
    main()
