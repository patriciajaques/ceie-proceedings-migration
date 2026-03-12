# src/adapters/base_ai_client.py
from abc import abstractmethod
from src.adapters.ai_client_interface import AIClientInterface
from src.config.config_loader import ConfigLoader
from src.config.credentials_manager_interface import CredentialsManagerInterface


class BaseAIClient(AIClientInterface):
    """
    Base class for AI client implementations.

    Implements common functionality for various AI clients
    and defines abstract methods that concrete classes must implement.
    """

    def __init__(self, config_loader: ConfigLoader, prompt_key: str):
        """
        Initialize the base AI client.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            prompt_key (str): Key for the prompt to be loaded.
        """
        self.prompt_key = prompt_key
        # Load prompt from YAML file
        self.system_message = config_loader.load_prompt(prompt_key)

        # Get credentials
        self.credentials = self.get_credentials_manager().get_credentials()
        self.api_key = self.credentials.get("api_key")

        # Initialize API client
        self.client = self.initialize_client()

    @abstractmethod
    def get_credentials_manager(self) -> CredentialsManagerInterface:
        """
        Return the appropriate credentials manager.

        Returns:
            CredentialsManagerInterface: The credentials manager.
        """
        pass

    @abstractmethod
    def initialize_client(self):
        """
        Initialize the API client.

        Returns:
            object: Initialized API client.
        """
        pass

    @abstractmethod
    def create_completion(self, user_message, is_json=False):
        """
        Create a completion using the API.

        Args:
            user_message (str): User message.
            is_json (bool, optional): Flag indicating if the response should be in JSON format.

        Returns:
            str: API response.
        """
        pass
