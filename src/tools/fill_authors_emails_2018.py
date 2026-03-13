import os
from pathlib import Path

from dotenv import load_dotenv

from src.adapters.langchain_client import LangChainClient
from src.config.config_loader import ConfigLoader
from src.services.authors_email_extractor import AuthorsEmailExtractor
from src.utils.pdf_processor import PDFProcessor


def main(
    use_llm: bool = False,
    max_pages: int = 5,
    max_articles: int | None = None,
) -> None:
    """
    Preenche a coluna authorEmail em Autores.csv e grava em Autores_emails_2018.csv.
    use_llm=False: usa apenas JSON de metadados e cache do website.
    use_llm=True: extrai e-mails dos PDFs via LLM (até max_pages páginas por PDF;
        texto é cortado em Resumo/Abstract só aqui; main.py continua enviando resumo para Artigos.csv).
    max_articles: se definido, processa só os primeiros N artigos (útil para testes). None = todos.
    """
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    load_dotenv(dotenv_path=project_root / ".env")

    config_loader = ConfigLoader("config/config.json")
    extractor = AuthorsEmailExtractor(config_loader)

    print("Carregando dados de autores a partir de Autores.csv...")
    authors_df = extractor.fill_missing_emails()

    if use_llm:
        from src.logging.json_logger import JsonLogger

        JsonLogger.initialize(config_loader)
        ai_client = LangChainClient(config_loader, "author_email_extraction")
        pdf_processor = PDFProcessor(extractor.pdf_folder)
        limit_msg = f" (primeiros {max_articles} artigos)" if max_articles else ""
        print(f"Extraindo e-mails dos artigos (PDF) via LLM{limit_msg}...")
        authors_df = extractor.fill_missing_emails_from_llm(
            ai_client,
            pdf_processor,
            max_pages_per_pdf=max_pages,
            start_df=authors_df,
            max_articles=max_articles,
        )

    print("Salvando resultado em Autores_emails_2018.csv...")
    extractor.save_authors_emails_2018(authors_df)


if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    use_llm = True
    max_pages = 5
    max_articles = None  # None = processar todos; número = só os primeiros N (teste)
    main(use_llm=use_llm, max_pages=max_pages, max_articles=max_articles)

