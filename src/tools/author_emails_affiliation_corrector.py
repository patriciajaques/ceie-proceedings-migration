import os
from pathlib import Path

from dotenv import load_dotenv

from src.adapters.langchain_client import LangChainClient
from src.config.config_loader import ConfigLoader
from src.services.authors_email_extractor import AuthorsEmailExtractor
from src.utils.pdf_processor import PDFProcessor


def main(
    use_llm_emails: bool = False,
    use_llm_affiliations: bool = False,
    max_pages: int = 5,
    max_articles: int | None = None,
) -> None:
    """
    Preenche/ajusta e-mails e afiliações dos autores em Autores.csv.

    - Sempre lê Autores.csv do ano configurado em config.json (output_dir/year/csv).
    - Sempre tenta preencher/ajustar e-mails a partir de metadados JSON e cache
      do website.

    use_llm_emails=False:
        Usa apenas JSON de metadados e cache do website para e-mails.
    use_llm_emails=True:
        Extrai e-mails dos PDFs via LLM (até max_pages páginas por PDF; texto
        é cortado em Resumo/Abstract só aqui; main.py continua enviando resumo
        para Artigos.csv).

    use_llm_affiliations=True:
        Quando True, usa LLM para recalcular/normalizar afiliações (pt e en)
        dos autores a partir dos PDFs, gerando um arquivo
        Autores_afiliacoes_{year}.csv no diretório de CSV do ano configurado.

    max_articles:
        Se definido, processa só os primeiros N artigos (útil para testes).
        None = processa todos.
    """
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    load_dotenv(dotenv_path=project_root / ".env")

    config_loader = ConfigLoader("config/config.json")
    extractor = AuthorsEmailExtractor(config_loader)

    print("Carregando dados de autores a partir de Autores.csv...")
    authors_df = extractor.fill_missing_emails()

    if use_llm_emails or use_llm_affiliations:
        from src.logging.json_logger import JsonLogger

        JsonLogger.initialize(config_loader)
        ai_client_emails = (
            LangChainClient(config_loader, "author_email_extraction")
            if use_llm_emails
            else None
        )
        ai_client_affiliations = (
            LangChainClient(config_loader, "author_affiliation_extraction")
            if use_llm_affiliations
            else None
        )
        pdf_processor = PDFProcessor(extractor.pdf_folder)
        limit_msg = f" (primeiros {max_articles} artigos)" if max_articles else ""

        if use_llm_emails:
            print(f"Extraindo e-mails dos artigos (PDF) via LLM{limit_msg}...")
            authors_df = extractor.fill_missing_emails_from_llm(
                ai_client_emails,
                pdf_processor,
                max_pages_per_pdf=max_pages,
                start_df=authors_df,
                max_articles=max_articles,
            )

        if use_llm_affiliations:
            print(
                "Extraindo e normalizando afiliações dos autores "
                f"(PDF) via LLM{limit_msg}..."
            )
            authors_df_affiliations = extractor.fill_affiliations_from_llm(
                ai_client_affiliations,
                pdf_processor,
                max_pages_per_pdf=max_pages,
                start_df=authors_df,
                max_articles=max_articles,
            )
            extractor.save_authors_affiliations_2018(authors_df_affiliations)

    print("Salvando resultado em Autores_emails_{year}.csv...")
    extractor.save_authors_emails_2018(authors_df)


if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    # Configuração padrão (ajuste conforme necessidade):
    # - use_llm_emails: controla uso de LLM para e-mails
    # - use_llm_affiliations: controla uso de LLM para afiliações
    use_llm_emails = False
    use_llm_affiliations = True
    max_pages = 1
    max_articles = None  # None = processar todos; número = só os primeiros N (teste)
    main(
        use_llm_emails=use_llm_emails,
        use_llm_affiliations=use_llm_affiliations,
        max_pages=max_pages,
        max_articles=max_articles,
    )
