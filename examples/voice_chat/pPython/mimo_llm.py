from typing import Any, Dict, Optional

import requests


def default_base_url_for_key(api_key: str) -> str:
    if (api_key or "").startswith("tp-"):
        return "https://token-plan-cn.xiaomimimo.com/v1"
    return "https://api.xiaomimimo.com/v1"


def auth_headers_for_key(api_key: str, base_url: str) -> Dict[str, str]:
    if (api_key or "").startswith("tp-") or "token-plan" in (base_url or ""):
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return {"api-key": api_key, "Content-Type": "application/json"}


class MiMoChat:
    DEFAULT_MODEL = "mimo-v2.5-pro"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None, system_prompt: str = ""):
        self.api_key = api_key
        self.base_url = (base_url or default_base_url_for_key(api_key)).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = system_prompt
        self.messages = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def chat(self, user_message: str, keep_history: bool = True) -> Dict[str, Any]:
        if keep_history:
            self.messages.append({"role": "user", "content": user_message})
            messages = self.messages
        else:
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": user_message})

        body = {"model": self.model, "messages": messages, "temperature": 0.7, "max_tokens": 1024}
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=auth_headers_for_key(self.api_key, self.base_url),
                timeout=60,
            )
            response.raise_for_status()
            choices = response.json().get("choices", [])
            if not choices:
                return {"success": False, "reply": "", "error": "API returned no choices"}
            reply = choices[0].get("message", {}).get("content", "")
            if keep_history:
                self.messages.append({"role": "assistant", "content": reply})
            return {"success": True, "reply": reply, "error": None}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "reply": "", "error": self._error_message(exc)}

    def clear_history(self):
        self.messages = []
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})

    @staticmethod
    def _error_message(exc: requests.exceptions.RequestException) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return f"API request failed: {exc}"
        try:
            detail = response.json()
            message = detail.get("error", {}).get("message") or str(exc)
        except Exception:
            message = str(exc)
        return f"API request failed: {message}"
