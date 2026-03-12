import os
from pathlib import Path

from src.config.config_loader import ConfigLoader
from src.utils.pdf_processor import PDFProcessor


def main(max_files: int = 5, pages_to_process: int = 2) -> None:
    """
    Executa a extração de texto dos primeiros `max_files` PDFs usando o
    PDFProcessor atual (PyMuPDF + heurística + fallback pdftotext) e
    imprime um resumo curto de cada artigo para inspeção manual.

    Isso é útil para verificar, em alguns casos concretos, se a acentuação
    e o encoding parecem melhores após as mudanças no pipeline de extração.
    """
    # Carrega configuração padrão do projeto
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config" / "config.json"
    config_loader = ConfigLoader(str(config_path))

    output_dir = config_loader.get_config_value("output_dir")
    year = config_loader.get_config_value("year")

    pdf_dir = Path(output_dir) / str(year) / "pdfs"
    if not pdf_dir.exists():
        raise FileNotFoundError(f"Diretório de PDFs não encontrado: {pdf_dir}")

    print(f"Usando diretório de PDFs: {pdf_dir}")

    processor = PDFProcessor(str(pdf_dir))

    # Coleta apenas alguns arquivos PDF para teste
    pdf_files = sorted(
        [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    )[:max_files]

    if not pdf_files:
        print("Nenhum PDF encontrado para teste.")
        return

    print(f"Testando extração em até {len(pdf_files)} PDFs...\n")

    for filename in pdf_files:
        pdf_path = os.path.join(pdf_dir, filename)
        print("=" * 80)
        print(f"Arquivo: {filename}")

        text_pages, num_pages = processor.extract_text_from_each_page(pdf_path)

        # Respeita o limite de páginas para inspeção
        if pages_to_process != -1 and pages_to_process > 0:
            text_pages = text_pages[:pages_to_process]

        joined_text = "\n--- PAGE BREAK ---\n".join(text_pages)
        preview = joined_text[:800].replace("\n", " ")

        print(f"Número de páginas extraídas: {num_pages}")
        print("Prévia do texto extraído (primeiros 800 caracteres):")
        print(preview)
        print()  # linha em branco entre artigos


if __name__ == "__main__":
    main()

