from __future__ import annotations

import json
import time

import httpx

from .config import get_settings


class OpenRouterClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.app_public_url,
            "X-OpenRouter-Title": "Enterprise Graph RAG",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format:
            body["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(self.settings.openrouter_max_retries + 1):
            try:
                with httpx.Client(timeout=self.settings.openrouter_timeout_seconds) as client:
                    response = client.post(
                        f"{self.settings.openrouter_base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    response.raise_for_status()
                    payload = response.json()
                choice = payload["choices"][0]["message"]["content"]
                if isinstance(choice, str):
                    try:
                        parsed = json.loads(choice)
                    except json.JSONDecodeError:
                        parsed = {"raw_content": choice}
                else:
                    parsed = choice
                return {"response": payload, "content": parsed}
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.openrouter_max_retries:
                    break
                time.sleep(min(3, attempt + 1))
        if last_error is None:
            raise RuntimeError("OpenRouter request failed without an explicit exception")
        raise last_error
