from __future__ import annotations

import json
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.adapters.ai_client_interface import AIClientInterface
from src.config.config_loader import ConfigLoader


class LangChainClient(AIClientInterface):
    """
    LangChain-backed client for multiple providers (OpenAI, Anthropic, etc.).

    Loads system prompt from config, resolves credentials, and exposes
    create_completion via AIClientInterface.
    """

    def __init__(self, config_loader: ConfigLoader, prompt_key: str) -> None:
        """
        Initialize the LangChain client.

        Args:
            config_loader: Configuration loader instance.
            prompt_key: Key for the prompt to be loaded from YAML.
        """
        self.prompt_key = prompt_key
        self.model_name = config_loader.get_config_value("engine")
        self.provider = self._detect_provider(self.model_name)
        self.max_tokens = config_loader.get_config_value("max_tokens", default=10000)
        self.system_message = config_loader.load_prompt(prompt_key)
        self.api_key = config_loader.get_api_key_for_provider(self.provider)
        self.client = self._initialize_client()
        # Set when the last completion returned empty content (for logging / debugging).
        self.last_response_metadata: dict[str, Any] | None = None

    def _detect_provider(self, model_name: str) -> str:
        """
        Detect provider from model name (e.g. gpt-*, claude-*, gemini-*).
        """
        model_lower = model_name.lower()

        if model_lower.startswith(("gpt-", "o1-", "o3-", "o4-")):
            return "openai"
        if model_lower.startswith(("claude-", "sonnet-")):
            return "anthropic"
        if model_lower.startswith(("gemini-", "palm-")):
            return "google"
        if model_lower.startswith("command"):
            return "cohere"
        return "openai"

    def _initialize_client(self) -> BaseChatModel:
        """Initialize the LangChain chat model for the detected provider."""
        common_params: dict = {
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }

        client: BaseChatModel
        if self.provider == "openai":
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
        Create a completion using LangChain.

        Args:
            user_message: User message.
            is_json: If True, request JSON-shaped output where supported.

        Returns:
            Model response text.

        Raises:
            Exception: Propagates API / LangChain failures (no silent empty return).
        """
        try:
            self.last_response_metadata = None

            messages = [
                SystemMessage(content=self.system_message),
                HumanMessage(content=user_message),
            ]

            client_to_use = self.client
            if is_json and self.provider == "openai":
                if self._supports_json_object():
                    client_to_use = self.client.bind(
                        response_format={"type": "json_object"}
                    )
                else:
                    user_message = (
                        f"{user_message}\n\nRetorne a resposta APENAS em formato JSON válido "
                        "(um único objeto), sem texto antes ou depois."
                    )
                    messages[1] = HumanMessage(content=user_message)
            elif is_json and self.provider == "anthropic":
                user_message = (
                    f"{user_message}\n\nRetorne a resposta APENAS em formato JSON válido."
                )
                messages[1] = HumanMessage(content=user_message)

            response = client_to_use.invoke(messages)

            if not response or self._message_content_is_empty(response):
                meta = self._serialize_aimessage_metadata(response)
                self.last_response_metadata = meta
                self._print_empty_response_debug(meta)
                return ""

            return response.content

        except Exception as e:
            error_msg = str(e)
            if "length limit" in error_msg.lower() or "token" in error_msg.lower():
                print(f"\n\nError: Limite de tokens. Detalhes: {error_msg}")
            else:
                print(f"\n\nError creating LangChain completion: {error_msg}")

            raise

    @staticmethod
    def _message_content_is_empty(response: Any) -> bool:
        """True if AIMessage has no usable text content."""
        if response is None:
            return True
        content = getattr(response, "content", None)
        if content is None:
            return True
        if isinstance(content, str):
            return len(content.strip()) == 0
        if isinstance(content, list):
            return all(
                not str(block.get("text", block) if isinstance(block, dict) else block).strip()
                for block in content
            )
        return False

    def _serialize_aimessage_metadata(self, response: Any) -> dict[str, Any]:
        """
        Build a JSON-safe dict for logging when the model returns empty content.

        Includes response_metadata (token usage, finish_reason, model id) when present.
        """
        out: dict[str, Any] = {"empty_content": True, "prompt_key": self.prompt_key}
        if response is None:
            out["message"] = "AIMessage was None"
            return out
        mid = getattr(response, "id", None)
        if mid:
            out["message_id"] = mid
        meta = getattr(response, "response_metadata", None) or {}
        if isinstance(meta, dict):
            out["response_metadata"] = self._json_safe(meta)
        else:
            out["response_metadata"] = str(meta)
        return out

    @staticmethod
    def _json_safe(obj: Any) -> Any:
        """Recursively convert objects to JSON-serializable structures."""
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, dict):
            return {str(k): LangChainClient._json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [LangChainClient._json_safe(x) for x in obj]
        if hasattr(obj, "model_dump"):
            try:
                return LangChainClient._json_safe(obj.model_dump())
            except Exception:
                pass
        if hasattr(obj, "__dict__"):
            return LangChainClient._json_safe(
                {k: v for k, v in vars(obj).items() if not k.startswith("_")}
            )
        return str(obj)

    def _print_empty_response_debug(self, meta: dict[str, Any]) -> None:
        """User-facing hint in Portuguese; full metadata goes to ai_calls.log.jsonl."""
        rm = meta.get("response_metadata")
        finish = None
        usage = None
        if isinstance(rm, dict):
            finish = rm.get("finish_reason")
            usage = rm.get("token_usage") or rm.get("usage")
        summary = {
            "etapa": self.prompt_key,
            "modelo": self.model_name,
            "finish_reason": finish,
            "token_usage": usage,
        }
        print(
            "\n\n[LLM] Resposta vazia. "
            f"Resumo: {json.dumps(summary, ensure_ascii=False)}",
            flush=True,
        )
        if isinstance(usage, dict):
            ct = usage.get("completion_tokens")
            if ct is not None and int(ct) == 0:
                print(
                    "[LLM] completion_tokens=0 — possível limite de saída, "
                    "filtro de conteúdo ou sobrecarga da API.",
                    flush=True,
                )

    def _is_temperature_restricted_model(self) -> bool:
        """
        Whether the model only supports default temperature (e.g. some gpt-5 / o*).
        """
        restricted_patterns = [
            "gpt-5-",
            "o3-",
            "o4-",
        ]
        return any(pattern in self.model_name for pattern in restricted_patterns)

    def _supports_json_object(self) -> bool:
        """Whether OpenAI json_object response_format is expected to work."""
        unsupported_patterns = [
            "gpt-5-nano-",
            "gpt-5-mini-",
        ]

        if any(pattern in self.model_name for pattern in unsupported_patterns):
            return False

        return True
