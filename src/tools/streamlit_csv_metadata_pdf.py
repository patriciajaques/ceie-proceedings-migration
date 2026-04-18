"""
Streamlit: primeira página do PDF + metadados de Artigos.csv / Autores.csv.

Não depende de arquivos de divergência em temp/ (ao contrário de
streamlit_verificacao_csv_vs_milanesa.py).
"""
import html
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config.config_loader import ConfigLoader
from src.tools.streamlit_verificacao_csv_vs_milanesa import (
    ROOT,
    _authors_from_csv,
    _display_pdf,
    _load_artigos_and_autores,
)

# Compact left-column metadata (smaller font, tight vertical rhythm).
_META_P_STYLE = (
    "font-size:0.82rem;line-height:1.28;margin:0.1em 0;padding:0;"
)
_META_H_STYLE = "font-size:1rem;margin:0.15em 0 0.2em 0;padding:0;"


def _build_article_list_all(artigos_df: pd.DataFrame) -> list[dict]:
    """All rows from Artigos.csv, sorted by seq."""
    artigos_df = artigos_df.copy()
    artigos_df["seq"] = artigos_df["seq"].astype(str).str.strip()
    artigos_df["idJEMS"] = artigos_df["idJEMS"].astype(str).str.strip()
    articles: list[dict] = []
    for _, row in artigos_df.iterrows():
        articles.append(
            {
                "seq": str(row["seq"]).strip(),
                "idJEMS": str(row["idJEMS"]).strip(),
                "artigo": row.to_dict(),
            }
        )
    articles.sort(
        key=lambda x: int(x["seq"]) if str(x["seq"]).isdigit() else 0
    )
    return articles


def main() -> None:
    st.set_page_config(
        page_title="Metadados CSV × PDF",
        layout="wide",
    )

    config = ConfigLoader("config/config.json")
    year = str(config.get_config_value("year", "2018"))
    output_dir = Path(config.get_config_value("output_dir", "output/"))

    try:
        artigos_df, autores_df = _load_artigos_and_autores(output_dir, year)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    articles = _build_article_list_all(artigos_df)
    if not articles:
        st.info("Nenhum artigo encontrado em Artigos.csv.")
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
    artigo = current["artigo"]

    with col_nav2:
        st.markdown(
            f"**Registro {current_idx + 1} de {len(articles)}** "
            f"(seq={current['seq']}, idJEMS={current['idJEMS']})"
        )

    left_col, right_col = st.columns(2)

    with left_col:
        st.markdown(
            f'<h3 style="{_META_H_STYLE}">Metadados do artigo (CSV)</h3>',
            unsafe_allow_html=True,
        )

        seq_val = str(artigo.get("seq", current["seq"]) or "").strip()
        idjems_val = str(
            artigo.get("idJEMS", current["idJEMS"]) or ""
        ).strip()
        st.markdown(
            f'<p style="{_META_P_STYLE}"><b>Seq:</b> '
            f"{html.escape(seq_val)} &nbsp; <b>idJEMS:</b> "
            f"{html.escape(idjems_val)}</p>",
            unsafe_allow_html=True,
        )

        title_orig = str(artigo.get("titleOrig", "") or "").strip()
        if title_orig:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Título (pt):</b> '
                f"{html.escape(title_orig)}</p>",
                unsafe_allow_html=True,
            )

        title_en = str(artigo.get("titleEn", "") or "").strip()
        if title_en:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Título (en):</b> '
                f"{html.escape(title_en)}</p>",
                unsafe_allow_html=True,
            )

        autores_list = _authors_from_csv(autores_df, seq_val)
        if not autores_list:
            st.markdown(
                f'<p style="{_META_P_STYLE}">'
                f"<b>Autores:</b> (sem autores no CSV)</p>",
                unsafe_allow_html=True,
            )
        else:
            author_lines = []
            for a in autores_list:
                name = a.get("name", "")
                email = a.get("email", "") or "-"
                aff = a.get("affiliation", "")
                parts = [name]
                if email:
                    parts.append(email)
                if aff:
                    parts.append(aff)
                author_lines.append(html.escape(" | ".join(parts)))
            body = "<br/>".join(author_lines)
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Autores:</b><br/>{body}</p>',
                unsafe_allow_html=True,
            )

        pages_val = str(artigo.get("pages", "") or "").strip()
        st.markdown(
            f'<p style="{_META_P_STYLE}"><b>Páginas:</b> '
            f"{html.escape(pages_val)}</p>",
            unsafe_allow_html=True,
        )

        lang = str(artigo.get("language", "") or "").strip()
        if lang:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Idioma:</b> '
                f"{html.escape(lang)}</p>",
                unsafe_allow_html=True,
            )

        section = str(artigo.get("sectionAbbrev", "") or "").strip()
        if section:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Seção:</b> '
                f"{html.escape(section)}</p>",
                unsafe_allow_html=True,
            )

        abstract_orig = str(artigo.get("abstractOrig", "") or "").strip()
        if abstract_orig:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Resumo (pt):</b> '
                f"{html.escape(abstract_orig)}</p>",
                unsafe_allow_html=True,
            )

        abstract_en = str(artigo.get("abstractEn", "") or "").strip()
        if abstract_en:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Resumo (en):</b> '
                f"{html.escape(abstract_en)}</p>",
                unsafe_allow_html=True,
            )

        kw_orig = str(artigo.get("keywordsOrig", "") or "").strip()
        if kw_orig:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Palavras-chave (pt):</b> '
                f"{html.escape(kw_orig)}</p>",
                unsafe_allow_html=True,
            )

        kw_en = str(artigo.get("keywordsEn", "") or "").strip()
        if kw_en:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Palavras-chave (en):</b> '
                f"{html.escape(kw_en)}</p>",
                unsafe_allow_html=True,
            )

    with right_col:
        pdfs_dir = output_dir / year / "pdfs"
        pdf_path = pdfs_dir / f"{current['idJEMS']}.pdf"
        if not pdf_path.exists():
            st.warning(
                f"PDF não encontrado em "
                f"{os.path.relpath(pdf_path, ROOT)}"
            )
        else:
            _display_pdf(pdf_path, height=800, top_crop=150)


if __name__ == "__main__":
    main()
