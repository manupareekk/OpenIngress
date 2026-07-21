"""Minimal OpenAI-compatible LLM client for agent exploration."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..config import Config


def _azure_base_url() -> Optional[str]:
    if Config.AZURE_OPENAI_BASE_URL:
        return Config.AZURE_OPENAI_BASE_URL.rstrip("/")
    if Config.AZURE_OPENAI_ENDPOINT:
        return f"{Config.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/v1"
    return None


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        from openai import OpenAI

        provider = Config.LLM_PROVIDER
        if provider == "azure_openai":
            self.api_key = api_key or Config.AZURE_OPENAI_API_KEY
            self.base_url = base_url or _azure_base_url()
            self.model = model or Config.AZURE_OPENAI_DEPLOYMENT
        else:
            self.api_key = api_key or Config.LLM_API_KEY
            self.base_url = base_url or Config.LLM_BASE_URL
            self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM API key is not configured.")
        if not self.base_url and Config.LLM_PROVIDER == "azure_openai":
            raise ValueError("Azure OpenAI base URL or endpoint is required.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60.0,
        )
        self.provider = provider

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if self.provider == "azure_openai":
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
        content = re.sub(r"^```(?:json)?\s*\n?", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\n?```\s*$", "", content).strip()
        if not content:
            raise ValueError("LLM returned an empty response.")
        return json.loads(content)
