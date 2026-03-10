from src.config.credentials_manager_interface import CredentialsManagerInterface
import os
from pathlib import Path
from dotenv import load_dotenv


class AnthropicCredentialsManager(CredentialsManagerInterface):
    """
    Class to manage Anthropic credentials from environment variables.
    """

    def __init__(self):
        # Load environment variables from project root .env
        project_root = Path(__file__).resolve().parent.parent
        env_path = project_root / ".env"
        load_dotenv(dotenv_path=env_path)

    def get_credentials(self):
        """
        Get Anthropic credentials from environment variables.

        Returns:
            dict: Dictionary containing the API key.
        """
        return {"api_key": os.environ.get("ANTHROPIC_API_KEY")}
