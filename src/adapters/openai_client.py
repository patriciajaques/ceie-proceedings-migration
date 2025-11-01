# src/adapters/openai_client.py
from openai import OpenAI
from src.adapters.base_ai_client import BaseAIClient
from src.config.config_loader import ConfigLoader
from src.config.openai_credentials_manager import OpenAICredentialsManager
from src.config.credentials_manager_interface import CredentialsManagerInterface


class OpenAIClient(BaseAIClient):
    """
    Client for the OpenAI API service.

    Implements the BaseAIClient interface to communicate
    with OpenAI services for text generation.
    """

    def __init__(self, config_loader: ConfigLoader, prompt_key: str):
        """
        Initialize the OpenAI client.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            prompt_key (str): Key for the prompt to be loaded.
        """
        self.model = config_loader.get_config_value("engine")
        super().__init__(config_loader, prompt_key)

    def get_credentials_manager(self) -> CredentialsManagerInterface:
        """
        Return the OpenAI credentials manager.

        Returns:
            CredentialsManagerInterface: The credentials manager.
        """
        return OpenAICredentialsManager()

    def initialize_client(self):
        """
        Initialize the OpenAI API client.

        Returns:
            OpenAI: Initialized OpenAI API client.
        """
        return OpenAI(api_key=self.api_key)

    def create_completion(self, user_message, is_json=False):
        """
        Create a completion using the OpenAI API.

        Args:
            user_message (str): User message.
            is_json (bool, optional): If True, requests response in JSON format.
                Defaults to False.

        Returns:
            str: OpenAI API response.
        """
        try:
            # Build base parameters
            params = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_message},
                    {"role": "user", "content": user_message},
                ],
                "max_completion_tokens": 4000,
            }

            # Some models (like gpt-5-nano) don't support json_object response_format
            # Check if model supports json_object format before setting it
            if is_json and self._supports_json_object():
                params["response_format"] = {"type": "json_object"}
            elif is_json:
                # For models that don't support json_object, we'll rely on the prompt
                # to instruct the model to return JSON (text format)
                pass

            # Some newer models don't support custom temperature values
            # Only set temperature if the model is known to support it
            # Models like gpt-5-mini only support default temperature (1)
            if not self._is_temperature_restricted_model():
                params["temperature"] = 0

            completion = self.client.chat.completions.create(**params)
            return completion.choices[0].message.content
        except Exception as e:
            print(f"\n\nError creating OpenAI completion: {e}")
            return ""

    def _is_temperature_restricted_model(self):
        """
        Check if the model only supports default temperature value.

        Some newer models like gpt-5-mini-* only support the default temperature (1)
        and will error if temperature=0 is explicitly set.

        Returns:
            bool: True if the model only supports default temperature.
        """
        restricted_patterns = [
            "gpt-5-",
            "o3-",
            "o4-",
        ]
        return any(pattern in self.model for pattern in restricted_patterns)

    def _supports_json_object(self):
        """
        Check if the model supports json_object response_format.

        Some models like gpt-5-nano-* don't support the json_object response_format
        and will return text even when requested. We need to handle this case.

        Returns:
            bool: True if the model supports json_object format.
        """
        # Models that don't support json_object format
        unsupported_patterns = [
            "gpt-5-nano-",
        ]

        # If model matches unsupported patterns, return False
        if any(pattern in self.model for pattern in unsupported_patterns):
            return False

        # Default to supporting json_object for other models
        return True
