# src/main.py
from src.config.config_loader import ConfigLoader
from src.adapters.langchain_client import LangChainClient
from src.services.article_extractor import ArticleExtractor
from src.services.migrator import Migrator
from src.logging.json_logger import JsonLogger
from src.utils.text_processor import TextProcessor
from src.graphs.migration.models import MigrationGraphInput
from src.graphs.migration.service import MigrationGraphService
import os


def main():
    """
    Main entry point for the application.
    Initializes components and executes the migration process.
    """
    # Config (loads config.json, prompts path, and .env via ConfigLoader)
    config_loader = ConfigLoader("config/config.json")

    # LangSmith rejects trace fields > ~25 MB; PDF-heavy prompts exceed that limit.
    # Optional key langchain_tracing in config.json overrides .env for this run.
    _lt = config_loader.get_config_value("langchain_tracing", default=None)
    if _lt is False:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
    elif _lt is True:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"

    # Initialize JsonLogger with configuration
    JsonLogger.initialize(config_loader)

    year = config_loader.get_config_value("year")
    print(f"Gerando os metadados dos anais do SBIE {year}")

    # Clientes de IA via LangChain (um por tipo de prompt)
    client_specs = {
        "article_ai_client": "article_extraction",
        "references_ai_client": "references_extraction",
        "field_completion_ai_client": "field_completion",
        "text_processing_client": "text_processing",
    }
    ai_clients = {
        key: LangChainClient(config_loader, prompt_key)
        for key, prompt_key in client_specs.items()
    }

    # Create text processor with AI client
    text_processor = TextProcessor(ai_clients["text_processing_client"])

    # Initialize the article extractor with AI clients and text processor
    article_extractor = ArticleExtractor(
        ai_clients["article_ai_client"],
        ai_clients["references_ai_client"],
        ai_clients["field_completion_ai_client"],
        text_processor,
    )

    migrator = Migrator(config_loader, article_extractor)

    # Configuration for execution
    pages_to_process = config_loader.get_config_value("pages_to_process")
    files_to_download = config_loader.get_config_value("files_to_download")
    article_offset = config_loader.get_config_value("article_offset", default=0)
    skip_fully_processed = config_loader.get_config_value(
        "skip_fully_processed_articles", default=True
    )
    _mc = config_loader.get_config_value("max_concurrency", default=None)
    max_concurrency = int(_mc) if _mc is not None else None

    # Execute the migration process via LangGraph (central pipeline)
    graph_service = MigrationGraphService(
        config_loader=config_loader,
        migrator=migrator,
    )
    result = graph_service.run(
        MigrationGraphInput(
            pages_to_process=pages_to_process,
            files_to_download=files_to_download,
            article_offset=int(article_offset),
            skip_fully_processed_articles=bool(skip_fully_processed),
            max_concurrency=max_concurrency,
        )
    )

    print(
        "Migration completed successfully. "
        f"Processed {len(result.articles)} articles."
    )


if __name__ == "__main__":
    # Clear the terminal screen
    os.system("cls" if os.name == "nt" else "clear")
    main()
