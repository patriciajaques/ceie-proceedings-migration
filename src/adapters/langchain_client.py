# src/adapters/langchain_client.py
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from src.adapters.base_ai_client import BaseAIClient
from src.config.config_loader import ConfigLoader
from src.config.credentials_manager_interface import CredentialsManagerInterface


class LangChainClient(BaseAIClient):
    """
    Client usando LangChain como abstração unificada para múltiplos provedores.

    Suporta OpenAI, Anthropic, Google, Cohere e outros através do LangChain.
    """

    def __init__(self, config_loader: ConfigLoader, prompt_key: str):
        """
        Initialize the LangChain client.

        Args:
            config_loader (ConfigLoader): Configuration loader instance.
            prompt_key (str): Key for the prompt to be loaded.
        """
        self.model_name = config_loader.get_config_value("engine")
        self.provider = self._detect_provider(self.model_name)
        self.max_tokens = config_loader.get_config_value("max_tokens", default=10000)
        super().__init__(config_loader, prompt_key)

    def _detect_provider(self, model_name: str) -> str:
        """
        Detecta o provedor baseado no nome do modelo.

        Args:
            model_name (str): Nome do modelo (ex: 'gpt-4', 'claude-3-opus', 'gemini-pro')

        Returns:
            str: Nome do provedor ('openai', 'anthropic', 'google', etc.)
        """
        model_lower = model_name.lower()

        if model_lower.startswith(("gpt-", "o1-", "o3-", "o4-")):
            return "openai"
        elif model_lower.startswith(("claude-", "sonnet-")):
            return "anthropic"
        elif model_lower.startswith(("gemini-", "palm-")):
            return "google"
        elif model_lower.startswith("command"):
            return "cohere"
        else:
            # Default para OpenAI se não conseguir detectar
            return "openai"

    def get_credentials_manager(self) -> CredentialsManagerInterface:
        """Retorna o gerenciador de credenciais apropriado."""
        if self.provider == "openai":
            from src.config.openai_credentials_manager import (
                OpenAICredentialsManager,
            )

            return OpenAICredentialsManager()
        elif self.provider == "anthropic":
            from src.config.anthropic_credentials_manager import (
                AnthropicCredentialsManager,
            )

            return AnthropicCredentialsManager()
        else:
            # Fallback para OpenAI
            from src.config.openai_credentials_manager import (
                OpenAICredentialsManager,
            )

            return OpenAICredentialsManager()

    def initialize_client(self) -> BaseChatModel:
        """
        Inicializa o cliente LangChain apropriado baseado no provedor.

        Returns:
            BaseChatModel: Cliente LangChain inicializado.
        """
        # Parâmetros comuns (max_tokens usa o default do modelo)
        common_params: dict = {
            "temperature": 0,
        }

        client: BaseChatModel
        if self.provider == "openai":
            # Verificar se o modelo suporta temperature customizada
            if self._is_temperature_restricted_model():
                common_params.pop("temperature", None)
            client = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                **common_params,
            )
        elif self.provider == "anthropic":
            client = ChatAnthropic(  # type: ignore[call-arg]
                model=self.model_name,
                api_key=self.api_key,
                **common_params,
            )
        elif self.provider == "google":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-untyped]

                client = ChatGoogleGenerativeAI(
                    model=self.model_name,
                    google_api_key=self.api_key,
                    **common_params,
                )
            except ImportError:
                print(
                    "Aviso: langchain-google-genai não está instalado. "
                    "Usando OpenAI como fallback."
                )
                client = ChatOpenAI(
                    model=self.model_name,
                    api_key=self.api_key,
                    **common_params,
                )
        else:
            client = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                **common_params,
            )
        return client

    def create_completion(self, user_message: str, is_json: bool = False) -> str:
        """
        Cria uma completion usando LangChain.

        Args:
            user_message (str): Mensagem do usuário.
            is_json (bool, optional): Se True, solicita resposta em formato JSON.
                Defaults to False.

        Returns:
            str: Resposta da API.
        """
        try:
            messages = [
                SystemMessage(content=self.system_message),
                HumanMessage(content=user_message),
            ]

            # Para modelos que suportam JSON mode
            client_to_use = self.client
            if is_json and self.provider == "openai":
                # Verificar se o modelo suporta json_object format
                if self._supports_json_object():
                    # No LangChain, response_format é passado via bind()
                    client_to_use = self.client.bind(
                        response_format={"type": "json_object"}
                    )
                else:
                    # Modelo não suporta json_object (ex.: gpt-5-mini); reforçar no prompt
                    user_message = (
                        f"{user_message}\n\nRetorne a resposta APENAS em formato JSON válido "
                        "(um único objeto), sem texto antes ou depois."
                    )
                    messages[1] = HumanMessage(content=user_message)
            elif is_json and self.provider == "anthropic":
                # Anthropic não tem JSON mode direto, mas podemos instruir via prompt
                user_message = f"{user_message}\n\nRetorne a resposta APENAS em formato JSON válido."
                messages[1] = HumanMessage(content=user_message)

            response = client_to_use.invoke(messages)
            
            # Verificar se a resposta está vazia ou None
            if not response or not response.content:
                if hasattr(response, "response_metadata") and response.response_metadata:
                    usage = response.response_metadata.get("usage")
                    if usage and getattr(usage, "completion_tokens", None) is not None:
                        print(
                            f"\n\nWarning: Resposta vazia (completion_tokens: {usage.completion_tokens}). "
                            "Pode ser limite de tokens do modelo."
                        )
                return ""
            
            return response.content

        except Exception as e:
            error_msg = str(e)
            # Detectar se o erro é relacionado a limite de tokens
            if "length limit" in error_msg.lower() or "token" in error_msg.lower():
                print(f"\n\nError: Limite de tokens. Detalhes: {error_msg}")
            else:
                print(f"\n\nError creating LangChain completion: {error_msg}")

            # Neste projeto, falhas de conexão/execução com o modelo via LangChain
            # devem abortar a execução em vez de retornar string vazia silenciosamente.
            raise

    def _is_temperature_restricted_model(self) -> bool:
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
        return any(pattern in self.model_name for pattern in restricted_patterns)

    def _supports_json_object(self) -> bool:
        """
        Check if the model supports json_object response_format.

        Some models like gpt-5-nano-* don't support the json_object response_format
        and will return text even when requested.

        Returns:
            bool: True if the model supports json_object format.
        """
        # Models that don't support json_object format
        unsupported_patterns = [
            "gpt-5-nano-",
            "gpt-5-mini-",  # não respeita response_format json_object; usar instrução no prompt
        ]

        # If model matches unsupported patterns, return False
        if any(pattern in self.model_name for pattern in unsupported_patterns):
            return False

        # Default to supporting json_object for other models
        return True
