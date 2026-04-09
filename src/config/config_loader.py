from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv


class ConfigLoader:
    """Loads JSON config, prompts YAML, and API keys from environment (.env)."""

    _MISSING = object()

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self._load_dotenv()
        self.config = self.load_configuration()

    def _load_dotenv(self) -> None:
        """
        Load `.env` from the project repository root.

        With the usual path `config/config.json`, resolved path is
        ``<root>/config/config.json``, so ``parent.parent`` is ``<root>`` — the
        same directory as ``readme.md`` and the ``config/`` folder.
        """
        cfg_path = Path(self.filepath).resolve()
        project_root = cfg_path.parent.parent
        load_dotenv(dotenv_path=project_root / ".env")

    def get_api_key_for_provider(self, provider: str) -> Optional[str]:
        """
        Return the API key from the environment for the given LLM provider.

        Falls back to OPENAI_API_KEY when the provider is unknown (same as
        previous OpenAI-based fallback for non-Anthropic paths).
        """
        env_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "cohere": "COHERE_API_KEY",
        }
        env_name = env_names.get(provider, "OPENAI_API_KEY")
        return os.environ.get(env_name)

    def get_config_value(self, key: str, default: Any = _MISSING) -> Any:
        """
        Gets a value from the configuration file.

        Args:
            key: The key to retrieve from the configuration.
            default: Default value if key is not found. If omitted,
                KeyError is raised when the key is missing. Passing
                default=None returns None when the key is missing.

        Returns:
            The value associated with the key, or default if key not found.

        Raises:
            KeyError: If the key is missing and no default is provided.
        """
        if default is self._MISSING:
            return self.config[key]
        return self.config.get(key, default)

    def load_configuration(self) -> dict:
        """
        Loads configuration from a JSON file.

        Returns:
            The configuration dict.

        Raises:
            ValueError: If the file extension is not .json
            FileNotFoundError: If the configuration file doesn't exist
            json.JSONDecodeError: If the JSON file is invalid
        """
        extension = os.path.splitext(self.filepath)[1].lower()

        if extension != ".json":
            raise ValueError(
                f"Unsupported file format: {extension}. "
                "Only .json files are supported"
            )

        with open(self.filepath, "r", encoding="utf-8") as file:
            return json.load(file)

    def load_prompt(self, prompt_key: str) -> str:
        """Load a specific prompt from the prompts file."""
        prompts_path = self.get_config_value("prompts_file")

        try:
            with open(prompts_path, "r", encoding="utf-8") as file:
                prompts = yaml.safe_load(file)

            if prompt_key not in prompts:
                print(
                    f"Aviso: Prompt '{prompt_key}' não encontrado no arquivo de prompts."
                )
                return ""

            return prompts[prompt_key]
        except Exception as e:
            print(f"Erro ao carregar prompt '{prompt_key}': {e}")
            return ""
