# src/adapters/model_factory.py
from typing import Dict, Type
from src.adapters.ai_client_interface import AIClientInterface
from src.adapters.base_ai_client import BaseAIClient
from src.config.config_loader import ConfigLoader


class ModelFactory:
    """
    Fábrica para criar instâncias de clientes de IA baseado na configuração.

    Suporta múltiplos provedores e métodos de criação:
    - Direto (OpenAIClient, AnthropicClient)
    - Via LangChain (LangChainClient - recomendado)
    """

    _providers: Dict[str, Type[BaseAIClient]] = {}
    _use_langchain: bool = True

    @classmethod
    def register_provider(cls, provider_name: str, client_class: Type[BaseAIClient]):
        """
        Registra um novo provedor na fábrica.

        Args:
            provider_name (str): Nome do provedor (ex: 'openai', 'anthropic').
            client_class (Type[BaseAIClient]): Classe do cliente.
        """
        cls._providers[provider_name] = client_class

    @classmethod
    def set_use_langchain(cls, use: bool):
        """
        Define se deve usar LangChain como camada de abstração.

        Args:
            use (bool): True para usar LangChain, False para usar clients diretos.
        """
        cls._use_langchain = use

    @classmethod
    def create_client(
        cls,
        config_loader: ConfigLoader,
        prompt_key: str,
        provider: str = None,
    ) -> AIClientInterface:
        """
        Cria um cliente de IA baseado na configuração.

        Args:
            config_loader (ConfigLoader): Loader de configuração.
            prompt_key (str): Chave do prompt a ser carregado.
            provider (str, optional): Força um provedor específico.
                Se None, detecta automaticamente pelo nome do modelo.

        Returns:
            AIClientInterface: Cliente de IA criado.
        """
        if cls._use_langchain:
            try:
                from src.adapters.langchain_client import LangChainClient

                return LangChainClient(config_loader, prompt_key)
            except ImportError as e:
                print(
                    f"Aviso: LangChain não está disponível ({e}). "
                    "Usando clients diretos como fallback."
                )
                cls._use_langchain = False

        # Fallback para criação direta se LangChain não estiver habilitado
        if provider:
            if provider not in cls._providers:
                raise ValueError(
                    f"Provider '{provider}' não registrado. "
                    f"Provedores disponíveis: {list(cls._providers.keys())}"
                )
            return cls._providers[provider](config_loader, prompt_key)

        # Detecção automática do provedor
        model_name = config_loader.get_config_value("engine", "")
        detected_provider = cls._detect_provider(model_name)

        if detected_provider not in cls._providers:
            raise ValueError(
                f"Provider '{detected_provider}' não registrado. "
                f"Provedores disponíveis: {list(cls._providers.keys())}"
            )

        return cls._providers[detected_provider](config_loader, prompt_key)

    @classmethod
    def _detect_provider(cls, model_name: str) -> str:
        """
        Detecta o provedor baseado no nome do modelo.

        Args:
            model_name (str): Nome do modelo.

        Returns:
            str: Nome do provedor detectado.
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

    @classmethod
    def create_all_clients(
        cls, config_loader: ConfigLoader
    ) -> Dict[str, AIClientInterface]:
        """
        Cria todos os clientes necessários para diferentes propósitos.

        Args:
            config_loader (ConfigLoader): Loader de configuração.

        Returns:
            Dict[str, AIClientInterface]: Dicionário com todos os clientes.
        """
        client_types = {
            "article_ai_client": "article_extraction",
            "references_ai_client": "references_extraction",
            "field_completion_ai_client": "field_completion",
            "affiliation_correction_client": "author_affiliation_correction",
            "text_processing_client": "text_processing",
        }

        return {
            client_key: cls.create_client(config_loader, prompt_key)
            for client_key, prompt_key in client_types.items()
        }


# Inicialização padrão da fábrica
def initialize_factory():
    """Inicializa a fábrica com os provedores padrão."""
    from src.adapters.openai_client import OpenAIClient
    from src.adapters.anthropic_client import AnthropicClient

    ModelFactory.register_provider("openai", OpenAIClient)
    ModelFactory.register_provider("anthropic", AnthropicClient)


# Inicializa automaticamente quando o módulo é importado
initialize_factory()
