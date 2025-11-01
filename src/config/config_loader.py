import yaml
import json
import os


class ConfigLoader:
    def __init__(self, filepath):
        self.filepath = filepath
        self.config = self.load_configuration()

    def get_config_value(self, key, default=None):
        """
        Gets a value from the configuration file.

        Args:
            key (str): The key to retrieve from the configuration.
            default: Default value to return if key is not found.

        Returns:
            Any: The value associated with the key in the configuration, or default if key not found.

        Raises:
            KeyError: If the key is not found in the configuration and no default is provided.
        """
        if default is None:
            return self.config[key]
        return self.config.get(key, default)

    def load_configuration(self):
        """
        Loads configuration from a JSON file.

        Returns:
            dict: The configuration data loaded from the JSON file.

        Raises:
            ValueError: If the file extension is not .json
            FileNotFoundError: If the configuration file doesn't exist
            json.JSONDecodeError: If the JSON file is invalid
        """
        extension = os.path.splitext(self.filepath)[1].lower()

        if extension != ".json":
            raise ValueError(
                f"Unsupported file format: {extension}. Only .json files are supported"
            )

        with open(self.filepath, "r", encoding="utf-8") as file:
            config = json.load(file)

        return config

    def load_prompt(self, prompt_key):
        """
        Load a specific prompt from the prompts file.
        """
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
