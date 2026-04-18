import html
import os
from pathlib import Path
from typing import Any

import fitz
import pandas as pd
import streamlit as st

from src.config.config_loader import ConfigLoader


ROOT = Path(__file__).resolve().parents[2]

# Compact metadata column (smaller font, tight vertical rhythm).
_META_P_STYLE = (
    "font-size:0.82rem;line-height:1.28;margin:0.1em 0;padding:0;"
)
_META_DIV_NOTE_STYLE = (
    "font-size:0.82rem;line-height:1.25;margin:0.05em 0 0.15em 0;"
)


def _load_latest_diverge_csv(temp_dir: Path) -> Path | None:
    pattern = "verificacao_csv_vs_milanesa_DIVERGE_*.csv"
    files = sorted(
        temp_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _load_artigos_and_autores(output_dir: Path, year: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    csv_dir = output_dir / year / "csv"
    artigos_path = csv_dir / "Artigos.csv"
    autores_path = csv_dir / "Autores.csv"

    if not artigos_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {artigos_path}")
    if not autores_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {autores_path}")

    artigos = pd.read_csv(artigos_path, delimiter=";")
    autores = pd.read_csv(autores_path, delimiter=";")
    return artigos, autores


def _authors_from_csv(authors_df: pd.DataFrame, seq: str) -> list[dict]:
    rows = authors_df[authors_df["article"].astype(str) == str(seq)]
    authors: list[dict] = []
    for _, r in rows.sort_values("order").iterrows():
        parts = [
            r.get("authorFirstName", ""),
            r.get("authorMiddleName", ""),
            r.get("authorLastName", ""),
        ]
        name = " ".join(
            str(p).strip()
            for p in parts
            if pd.notna(p) and str(p).strip()
        )
        affiliation_raw = r.get("authorAffiliation", "")
        affiliation = (
            ""
            if pd.isna(affiliation_raw)
            else str(affiliation_raw or "").strip()
        )
        email_raw = r.get("authorEmail", "")
        email = (
            ""
            if pd.isna(email_raw)
            else str(email_raw or "").strip()
        )
        if name:
            authors.append(
                {
                    "name": name,
                    "email": email,
                    "affiliation": affiliation,
                }
            )
    return authors


def _display_pdf(
    pdf_path: Path,
    height: int = 800,
    top_crop: int = 0,
) -> None:
    """Display only the first page of the PDF, optionally hiding the top (header)."""
    if not pdf_path.exists():
        st.warning("PDF não encontrado para este artigo.")
        return

    try:
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            st.warning("PDF sem páginas.")
            doc.close()
            return
        page = doc[0]
        mat = fitz.Matrix(2.0, 2.0)
        # Clip top of page to hide header (top_crop in pixels at 2x ≈ half in points)
        clip = None
        if top_crop > 0:
            # PDF units: 72 points per inch; clip from top_crop (pixel hint) to points
            top_pt = top_crop * 72 / 96  # ~96 DPI reference
            r = page.rect
            clip = fitz.Rect(0, top_pt, r.width, r.height)
        pix = page.get_pixmap(matrix=mat, alpha=False, clip=clip)
        png_bytes = pix.tobytes("png")
        doc.close()
    except Exception as e:
        st.warning(f"Erro ao abrir PDF: {e}")
        return

    st.image(png_bytes, use_container_width=True)


def _build_article_list(
    diverge_df: pd.DataFrame,
    artigos_df: pd.DataFrame,
) -> list[dict]:
    diverge_df = diverge_df.copy()
    diverge_df["idJEMS"] = diverge_df["idJEMS"].astype(str).str.strip()
    diverge_df["seq"] = diverge_df["seq"].astype(str).str.strip()

    artigos_df = artigos_df.copy()
    artigos_df["idJEMS"] = artigos_df["idJEMS"].astype(str).str.strip()
    artigos_df["seq"] = artigos_df["seq"].astype(str).str.strip()

    articles = []
    grouped = diverge_df.groupby(["idJEMS", "seq"])
    for (idjems, seq), group in grouped:
        art_row = artigos_df[artigos_df["idJEMS"] == idjems]
        if art_row.empty:
            art_row = artigos_df[artigos_df["seq"] == seq]
        art_record = art_row.iloc[0].to_dict() if not art_row.empty else {}
        articles.append(
            {
                "idJEMS": idjems,
                "seq": seq,
                "divergences": group,
                "artigo": art_record,
            }
        )

    articles.sort(key=lambda x: int(x["seq"]) if str(x["seq"]).isdigit() else 0)
    return articles


def _emit_field_divergence_note(
    campo_name: str,
    div_row: Any,
    color: str,
) -> None:
    """Milanesa divergence note below a field (same rules as render_field)."""
    if div_row is None or div_row.get("status") == "OK":
        return
    raw_mil = div_row.get("valor_milanesa", "")
    mil_val = "" if pd.isna(raw_mil) else str(raw_mil or "").strip()
    status = str(div_row.get("status", "") or "").strip()
    if status == "AUSENTE_MILANESA":
        extra = (
            "Artigo não encontrado no Milanesa "
            "(idJEMS não retornado pelo parser)"
        )
    else:
        if mil_val:
            extra = f"Milanesa: {mil_val}"
        else:
            if campo_name in {"abstractOrig", "abstractEn"}:
                extra = ""
            else:
                extra = "Valor ausente no Milanesa"

    if extra:
        st.markdown(
            f'<p style="{_META_DIV_NOTE_STYLE}">'
            f"<span style='color:{color}; font-size:0.88em'>"
            f"[{status}] {html.escape(extra)}"
            f"</span></p>",
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(
        page_title="Verificação CSV vs Milanesa",
        layout="wide",
    )

    config = ConfigLoader("config/config.json")
    year = str(config.get_config_value("year", "2018"))
    output_dir = Path(config.get_config_value("output_dir", "output/"))
    temp_dir = ROOT / "temp"

    latest_csv = _load_latest_diverge_csv(temp_dir)
    if latest_csv is None:
        st.error("Nenhum arquivo de divergências encontrado em temp/.")
        return

    diverge_df = pd.read_csv(latest_csv, delimiter=";")

    try:
        artigos_df, autores_df = _load_artigos_and_autores(output_dir, year)
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    articles = _build_article_list(diverge_df, artigos_df)
    if not articles:
        st.info("Nenhum artigo com divergência encontrado no arquivo.")
        return

    # Navegação por seq diretamente a partir da sidebar
    st.sidebar.markdown("### Arquivo de divergências")
    st.sidebar.write(str(latest_csv.relative_to(ROOT)))

    seq_options = [a["seq"] for a in articles]

    if "idx" not in st.session_state:
        st.session_state["idx"] = 0

    # Selectbox para pular diretamente para um artigo (seq)
    try:
        current_idx_for_select = min(
            max(st.session_state["idx"], 0),
            len(seq_options) - 1,
        )
    except KeyError:
        current_idx_for_select = 0

    selected_seq = st.sidebar.selectbox(
        "Ir diretamente para o artigo (seq)",
        options=seq_options,
        index=current_idx_for_select,
    )
    if selected_seq in seq_options:
        target_idx = seq_options.index(selected_seq)
        st.session_state["idx"] = target_idx

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

    artigo = current["artigo"]
    divergences: pd.DataFrame = current["divergences"]

    campos_div = {
        row["campo"]: row for _, row in divergences.iterrows()
    }

    left_col, right_col = st.columns(2)

    with left_col:
        st.markdown(
            f'<h3 style="font-size:1rem;margin:0.15em 0 0.2em 0;padding:0;">'
            f"Metadados do artigo (CSV)</h3>",
            unsafe_allow_html=True,
        )

        def render_field(
            label: str,
            field_key: str | None,
            value: str,
        ) -> None:
            campo_name = field_key or label
            div_row = campos_div.get(campo_name)
            is_div = div_row is not None and div_row.get("status") != "OK"
            color = "red" if is_div else "black"

            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>{html.escape(label)}:</b> '
                f"<span style='color:{color}'>{html.escape(value)}</span></p>",
                unsafe_allow_html=True,
            )

            if is_div and div_row is not None:
                _emit_field_divergence_note(campo_name, div_row, color)

        seq_val = str(artigo.get("seq", current["seq"]) or "").strip()
        idjems_val = str(artigo.get("idJEMS", current["idJEMS"]) or "").strip()

        row_seq = campos_div.get("seq")
        row_id = campos_div.get("idJEMS")
        is_div_seq = row_seq is not None and row_seq.get("status") != "OK"
        is_div_id = row_id is not None and row_id.get("status") != "OK"
        color_seq = "red" if is_div_seq else "black"
        color_id = "red" if is_div_id else "black"
        st.markdown(
            f'<p style="{_META_P_STYLE}"><b>Seq:</b> '
            f"<span style='color:{color_seq}'>{html.escape(seq_val)}</span>"
            f' &nbsp; <b>idJEMS:</b> '
            f"<span style='color:{color_id}'>{html.escape(idjems_val)}</span>"
            f"</p>",
            unsafe_allow_html=True,
        )
        if is_div_seq and row_seq is not None:
            _emit_field_divergence_note("seq", row_seq, color_seq)
        if is_div_id and row_id is not None:
            _emit_field_divergence_note("idJEMS", row_id, color_id)

        title_orig = str(artigo.get("titleOrig", "") or "").strip()
        render_field("Título (pt)", "titleOrig", title_orig)

        title_en = str(artigo.get("titleEn", "") or "").strip()
        if title_en:
            render_field("Título (en)", "titleEn", title_en)

        autores_list = _authors_from_csv(autores_df, seq_val)
        autores_div_row = campos_div.get("autores")
        autores_is_div = (
            autores_div_row is not None
            and autores_div_row.get("status") != "OK"
        )
        autores_color = "red" if autores_is_div else "black"

        if not autores_list:
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Autores:</b> '
                f"<span style='color:{autores_color}'>"
                f"(sem autores no CSV)</span></p>",
                unsafe_allow_html=True,
            )
        else:
            lines = []
            for a in autores_list:
                name = a.get("name", "")
                email = a.get("email", "") or "-"
                aff = a.get("affiliation", "")

                parts = [name]
                if email:
                    parts.append(email)
                if aff:
                    parts.append(aff)
                text = " | ".join(parts)
                lines.append(
                    f"<span style='color:{autores_color}'>"
                    f"{html.escape(text)}</span>"
                )
            body = "<br/>".join(lines)
            st.markdown(
                f'<p style="{_META_P_STYLE}"><b>Autores:</b><br/>{body}</p>',
                unsafe_allow_html=True,
            )

        if autores_is_div:
            raw_mil_aut = autores_div_row.get("valor_milanesa", "")
            mil_aut = "" if pd.isna(raw_mil_aut) else str(raw_mil_aut or "").strip()
            status_aut = str(autores_div_row.get("status", "") or "").strip()
            extra_aut = (
                f"Milanesa: {mil_aut}"
                if mil_aut
                else "Autores divergentes em relação ao Milanesa"
            )
            st.markdown(
                f'<p style="{_META_DIV_NOTE_STYLE}">'
                f"<span style='color:{autores_color}; font-size:0.88em'>"
                f"[{html.escape(status_aut)}] {html.escape(extra_aut)}"
                f"</span></p>",
                unsafe_allow_html=True,
            )


        pages_val = str(artigo.get("pages", "") or "").strip()
        render_field("Páginas", "pages", pages_val)

        lang = str(artigo.get("language", "") or "").strip()
        if lang:
            render_field("Idioma", "language", lang)

        section = str(artigo.get("sectionAbbrev", "") or "").strip()
        if section:
            render_field("Seção", "sectionAbbrev", section)

        abstract_orig = str(artigo.get("abstractOrig", "") or "").strip()
        if abstract_orig:
            render_field("Resumo (pt)", "abstractOrig", abstract_orig)

        abstract_en = str(artigo.get("abstractEn", "") or "").strip()
        if abstract_en:
            render_field("Resumo (en)", "abstractEn", abstract_en)

        kw_orig = str(artigo.get("keywordsOrig", "") or "").strip()
        if kw_orig:
            render_field("Palavras‑chave (pt)", "keywordsOrig", kw_orig)

        kw_en = str(artigo.get("keywordsEn", "") or "").strip()
        if kw_en:
            render_field("Palavras‑chave (en)", "keywordsEn", kw_en)

    with right_col:
        pdfs_dir = output_dir / year / "pdfs"
        pdf_path = pdfs_dir / f"{current['idJEMS']}.pdf"
        if not pdf_path.exists():
            st.warning(
                f"PDF não encontrado em "
                f"{os.path.relpath(pdf_path, ROOT)}"
            )
        else:
            # top_crop define quantos pixels do topo do PDF serão "cortados" visualmente
            _display_pdf(pdf_path, height=800, top_crop=150)


if __name__ == "__main__":
    main()

