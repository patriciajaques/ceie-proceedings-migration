# src/main.py
from src.config.config_loader import ConfigLoader
from src.adapters.langchain_client import LangChainClient
from src.services.article_extractor import ArticleExtractor
from src.services.migrator import Migrator
from src.logging.json_logger import JsonLogger
from src.utils.text_processor import TextProcessor
import os
from pathlib import Path
from dotenv import load_dotenv


def main():
    """
    Main entry point for the application.
    Initializes components and executes the migration process.
    """
    # Load environment variables from project root .env
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path)

    # Load configuration
    config_loader = ConfigLoader("config/config.json")

    # Initialize JsonLogger with configuration
    JsonLogger.initialize(config_loader)

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

    # Caminho do cache de extração para execução incremental
    output_dir = config_loader.get_config_value("output_dir")
    year = config_loader.get_config_value("year")
    extraction_cache_path = os.path.join(output_dir, str(year), "logs", "extraction_cache.json")

    # Initialize the article extractor with AI clients and text processor
    article_extractor = ArticleExtractor(
        ai_clients["article_ai_client"],
        ai_clients["references_ai_client"],
        ai_clients["field_completion_ai_client"],
        text_processor,
        extraction_cache_path=extraction_cache_path,
    )

    migrator = Migrator(config_loader, article_extractor)

    # Configuration for execution
    pages_to_process = config_loader.get_config_value("pages_to_process")
    files_to_download = config_loader.get_config_value("files_to_download")

    # Execute the migration process
    articles = migrator.migrate(pages_to_process, files_to_download)

    print(f"Migration completed successfully. Processed {len(articles)} articles.")


if __name__ == "__main__":
    # Clear the terminal screen
    os.system("cls" if os.name == "nt" else "clear")
    main()
