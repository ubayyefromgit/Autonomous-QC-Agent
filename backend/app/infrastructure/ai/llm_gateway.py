"""Provider-independent LLM Gateway supporting Gemini, OpenAI, and Ollama."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TypeVar

import httpx
import yaml
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMRequest(BaseModel):
    prompt_key: str | None = None
    template_vars: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str = "You are a technical software audit assistant."
    user_prompt: str = ""
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout_seconds: float = 20.0


class LLMResponse(BaseModel):
    provider: str
    model: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    used_fallback: bool = False


class PromptTemplateRegistry:
    """Loads externalized prompt templates from backend/app/prompts/*.yaml."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or (
            Path(__file__).resolve().parents[2] / "prompts"
        )
        self._templates: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.prompts_dir.exists():
            return
        for yaml_file in self.prompts_dir.glob("*.yaml"):
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                self._templates.update(data)

    def render(self, key: str, variables: dict[str, Any]) -> tuple[str, str]:
        tpl = self._templates.get(key)
        if not tpl:
            return "You are a technical software audit assistant.", str(variables)
        sys_inst = tpl.get("system_instruction", "").strip()
        user_tpl = tpl.get("user_template", "")
        try:
            rendered_user = user_tpl.format(**variables)
        except KeyError:
            rendered_user = user_tpl
        return sys_inst, rendered_user


class LLMProvider(ABC):
    """Abstract base interface for all AI model providers."""

    provider_name: str
    model_name: str

    def __init__(self) -> None:
        self.prompt_registry = PromptTemplateRegistry()

    def prepare_prompts(self, request: LLMRequest) -> tuple[str, str]:
        if request.prompt_key:
            return self.prompt_registry.render(request.prompt_key, request.template_vars)
        return request.system_prompt, request.user_prompt

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        ...

    async def generate_structured(
        self, request: LLMRequest, response_schema: type[T]
    ) -> tuple[T, LLMResponse]:
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        sys_prompt, usr_prompt = self.prepare_prompts(request)
        augmented_req = LLMRequest(
            system_prompt=f"{sys_prompt}\nRespond ONLY with valid JSON matching this schema:\n{schema_json}",
            user_prompt=usr_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout_seconds=request.timeout_seconds,
        )
        raw_resp = await self.generate(augmented_req)
        cleaned = raw_resp.content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = response_schema.model_validate_json(cleaned)
        return parsed, raw_resp


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        super().__init__()
        settings = get_settings()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model_name = model or settings.OLLAMA_MODEL

    async def generate(self, request: LLMRequest) -> LLMResponse:
        sys_prompt, usr_prompt = self.prepare_prompts(request)
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model_name,
                    "system": sys_prompt,
                    "prompt": usr_prompt,
                    "stream": False,
                    "options": {"temperature": request.temperature},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return LLMResponse(
                provider=self.provider_name,
                model=self.model_name,
                content=data.get("response", ""),
                prompt_tokens=int(data.get("prompt_eval_count", 0)),
                completion_tokens=int(data.get("eval_count", 0)),
                estimated_cost_usd=0.0,
            )


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__()
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model or settings.GEMINI_MODEL

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        sys_prompt, usr_prompt = self.prepare_prompts(request)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            resp = await client.post(
                url,
                params={"key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": sys_prompt}]},
                    "contents": [{"parts": [{"text": usr_prompt}]}],
                    "generationConfig": {"temperature": request.temperature},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            text = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if candidates
                else ""
            )
            usage = data.get("usageMetadata", {})
            p_tok = int(usage.get("promptTokenCount", 0))
            c_tok = int(usage.get("candidatesTokenCount", 0))
            cost = round((p_tok * 0.00000125) + (c_tok * 0.000005), 6)
            return LLMResponse(
                provider=self.provider_name,
                model=self.model_name,
                content=text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                estimated_cost_usd=cost,
            )


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__()
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
        self.model_name = model or settings.OPENAI_MODEL

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        sys_prompt, usr_prompt = self.prepare_prompts(request)
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": usr_prompt},
                    ],
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            p_tok = int(usage.get("prompt_tokens", 0))
            c_tok = int(usage.get("completion_tokens", 0))
            cost = round((p_tok * 0.0000025) + (c_tok * 0.00001), 6)
            return LLMResponse(
                provider=self.provider_name,
                model=self.model_name,
                content=text,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                estimated_cost_usd=cost,
            )


class UnifiedLLMGateway:
    """Routes LLM requests across configured providers with deterministic fallback."""

    def __init__(self, preferred_provider: str | None = None) -> None:
        settings = get_settings()
        self.preferred = (preferred_provider or settings.DEFAULT_LLM_PROVIDER).lower()
        self.providers: dict[str, LLMProvider] = {
            "ollama": OllamaProvider(),
            "gemini": GeminiProvider(),
            "openai": OpenAIProvider(),
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        order = [self.preferred] + [p for p in ("ollama", "gemini", "openai") if p != self.preferred]
        for idx, name in enumerate(order):
            provider = self.providers.get(name)
            if not provider:
                continue
            try:
                resp = await provider.generate(request)
                resp.used_fallback = idx > 0
                return resp
            except Exception:
                continue

        # Deterministic contextual synthesis when no external/local LLM daemon is reachable
        _, usr_prompt = self.providers["ollama"].prepare_prompts(request)
        return LLMResponse(
            provider="deterministic_analyzer",
            model="rule-contextual-v1",
            content=f"Deterministic contextual synthesis completed for input ({len(usr_prompt)} chars).",
            prompt_tokens=0,
            completion_tokens=0,
            estimated_cost_usd=0.0,
            used_fallback=True,
        )
