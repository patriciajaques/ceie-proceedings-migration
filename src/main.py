# src/main.py
from src.config.config_loader import ConfigLoader
from src.adapters.model_factory import ModelFactory
from src.services.article_extractor import ArticleExtractor
from src.services.migrator import Migrator
from src.logging.json_logger import JsonLogger
from src.utils.text_processor import TextProcessor
import os
from dotenv import load_dotenv


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

    # Configurar uso do LangChain (pode ser controlado por variável de ambiente)
    # Por padrão, usa LangChain para abstração unificada
    use_langchain = os.getenv("USE_LANGCHAIN", "true").lower() == "true"
    ModelFactory.set_use_langchain(use_langchain)

    # Criar todos os clientes necessários usando a fábrica
    # A fábrica detecta automaticamente o provedor baseado no nome do modelo no config.json
    ai_clients = ModelFactory.create_all_clients(config_loader)

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
