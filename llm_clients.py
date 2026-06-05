import json
import urllib.error
import urllib.request


class LlmError(Exception):
    pass


def _json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class OpenAIStyleChatClient(object):
    def __init__(self, base_url, api_key, model, timeout_seconds=30, opener=None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout_seconds = int(timeout_seconds)
        self.opener = opener

    @property
    def is_configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def _open(self, request):
        if self.opener is not None:
            return self.opener(request, timeout=self.timeout_seconds)
        return urllib.request.urlopen(request, timeout=self.timeout_seconds)

    def chat(self, system_prompt, user_prompt, temperature=0.2, response_format=None, max_tokens=None):
        if not self.is_configured:
            raise LlmError("LLM client is not fully configured.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=_json_dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with self._open(request) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LlmError("HTTP {0}: {1}".format(exc.code, body))
        except urllib.error.URLError as exc:
            raise LlmError("Network error: {0}".format(exc))

        try:
            payload = json.loads(raw)
        except ValueError:
            raise LlmError("LLM response was not valid JSON.")

        choices = payload.get("choices") or []
        if not choices:
            raise LlmError("LLM response did not contain choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            content = "".join(parts)
        if not isinstance(content, str):
            raise LlmError("LLM response content was empty.")
        return content.strip()


class AnthropicChatClient(object):
    """女娲平台 Anthropic 协议适配器（支持 thinking + text 双 block）"""

    def __init__(self, base_url, api_key, model, timeout_seconds=120, opener=None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.timeout_seconds = int(timeout_seconds)
        self.opener = opener

    @property
    def is_configured(self):
        return bool(self.base_url and self.api_key and self.model)

    def _open(self, request):
        if self.opener is not None:
            return self.opener(request, timeout=self.timeout_seconds)
        return urllib.request.urlopen(request, timeout=self.timeout_seconds)

    def chat(self, system_prompt, user_prompt, temperature=0.2, response_format=None, max_tokens=4096):
        if not self.is_configured:
            raise LlmError("Anthropic client is not fully configured.")

        messages = []
        if system_prompt:
            messages.append({"role": "assistant", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        request = urllib.request.Request(
            self.base_url + "/v1/messages",
            data=_json_dumps(payload),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with self._open(request) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LlmError("HTTP {0}: {1}".format(exc.code, body))
        except urllib.error.URLError as exc:
            raise LlmError("Network error: {0}".format(exc))

        try:
            payload = json.loads(raw)
        except ValueError:
            raise LlmError("Anthropic response was not valid JSON.")

        content_blocks = payload.get("content") or []
        text_parts = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        if not text_parts:
            raise LlmError("Anthropic response did not contain text content.")
        return "".join(text_parts).strip()


def parse_json_object(raw_text):
    text = (raw_text or "").strip()
    if not text:
        raise LlmError("Empty LLM output.")
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)
