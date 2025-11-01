# src/main.py
from src.config.config_loader import ConfigLoader
from src.adapters.openai_client import OpenAIClient
from src.adapters.anthropic_client import AnthropicClient
from src.adapters.ai_client_interface import AIClientInterface
from src.services.article_extractor import ArticleExtractor
from src.services.migrator import Migrator
from src.logging.json_logger import JsonLogger
from src.utils.text_processor import TextProcessor
import os
from dotenv import load_dotenv
from typing import Dict


def create_ai_clients(
    config_loader: ConfigLoader, use_openai: bool
) -> Dict[str, AIClientInterface]:
    """
    Creates AI client instances based on configuration.
    """
    client_class = OpenAIClient if use_openai else AnthropicClient

    # Definir os tipos de clientes e seus respectivos prompts
    client_types = {
        "article_ai_client": "article_extraction",
        "references_ai_client": "references_extraction",
        "field_completion_ai_client": "field_completion",
        "affiliation_correction_client": "author_affiliation_correction",
        "text_processing_client": "text_processing",
    }

    # Criar clientes para diferentes propósitos com diferentes prompts
    return {
        client_key: client_class(config_loader, prompt_key)
        for client_key, prompt_key in client_types.items()
    }


def main():
    """
    Main entry point for the application.
    Initializes components and executes the migration process.
    """
    # Load environment variables
    load_dotenv()

    # Load configuration
    config_loader = ConfigLoader("config/config.json")

    # Initialize JsonLogger with configuration
    JsonLogger.initialize(config_loader)

    # Determine which AI client to use based on environment variable
    use_openai = os.getenv("USE_OPENAI", "true").lower() == "true"

    # Create all required AI clients
    ai_clients = create_ai_clients(config_loader, use_openai)

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

    # Execute the migration process
    articles = migrator.migrate(pages_to_process, files_to_download)

    print(f"Migration completed successfully. Processed {len(articles)} articles.")


if __name__ == "__main__":
    # Clear the terminal screen
    os.system("cls" if os.name == "nt" else "clear")
    main()
