from configs import setup_logger
from langchain_openai import ChatOpenAI
from configs import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
)
from token_tracker import TokenCallback

_TOKEN_CALLBACK = None


def _get_token_callback():
    global _TOKEN_CALLBACK
    if _TOKEN_CALLBACK is None:
        _TOKEN_CALLBACK = TokenCallback()
    return _TOKEN_CALLBACK


class BaseAgent:
    def __init__(self, model_name: str, logger: str = "general_logger"):
        self.model_name = model_name.lower()
        self.logger = setup_logger(logger)
        self.callbacks = [_get_token_callback()]

    def _build(self, **kwargs):
        return ChatOpenAI(
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            callbacks=self.callbacks,
            **kwargs,
        )

    def initagent(self) -> ChatOpenAI:
        if "deepseek" in self.model_name:
            self.model = self._build(model=self.model_name, api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        elif "anthropic" in self.model_name:
            self.model = self._build(model=self.model_name, api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)
        elif "gemini" in self.model_name:
            self.model = self._build(model=self.model_name, api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)
        elif "openai" in self.model_name or "gpt" in self.model_name or "o1" in self.model_name or "o3" in self.model_name:
            self.model = self._build(model=self.model_name, api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        else:
            self.logger.warning(f"Model {self.model_name} not recognized. Using default ChatOpenAI without API key.")
            self.model = ChatOpenAI(model=self.model_name, temperature=0.0, callbacks=self.callbacks)
        return self.model
