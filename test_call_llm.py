import urllib.request, json, sys

from config import (
    MIMO_API_KEY, MIMO_CHAT_URL, MIMO_MODEL, MIMO_AUTH_TYPE,
    MINIMAX_API_KEY, MINIMAX_CHAT_URL, MINIMAX_MODEL, MINIMAX_AUTH_TYPE,
    GLM_API_KEY, GLM_CHAT_URL, GLM_MODEL, GLM_AUTH_TYPE,
)


def auth_headers(api_key, auth_type):
    if (auth_type or "api-key").lower() == "bearer":
        return {"Authorization": "Bearer " + api_key}
    return {"api-key": api_key}


def provider_config():
    if MIMO_API_KEY:
        return MIMO_CHAT_URL, MIMO_API_KEY, MIMO_MODEL, auth_headers(MIMO_API_KEY, MIMO_AUTH_TYPE), "max_completion_tokens", True
    if MINIMAX_API_KEY:
        return MINIMAX_CHAT_URL, MINIMAX_API_KEY, MINIMAX_MODEL, auth_headers(MINIMAX_API_KEY, MINIMAX_AUTH_TYPE), "max_tokens", False
    if GLM_API_KEY:
        return GLM_CHAT_URL, GLM_API_KEY, GLM_MODEL, auth_headers(GLM_API_KEY, GLM_AUTH_TYPE), "max_tokens", False
    print("Error: configure MIMO_API_KEY, MINIMAX_API_KEY, or GLM_API_KEY.")
    sys.exit(1)


url, api_key, model, auth_headers, token_field, include_thinking = provider_config()
system_prompt = (
    "你是一个旅游意图分类助手。根据用户的自然语言输入，判断用户的真实意图类型。\n"
    "intent_type 只能是以下三种之一：\n"
    "1. single_poi：用户只想去一个地方\n"
    "2. simple_route：用户想去 2-3 个地方简单逛逛\n"
    "3. complex_route：用户要求规划完整路线\n\n"
    "必须只输出 JSON 格式，不要任何其他文字："
    '{"intent_type": "...", "reason": "..."}'
)
user_prompt = "想吃火锅"

payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ],
    "temperature": 0.1,
    "stream": False,
}
payload[token_field] = 200
if include_thinking:
    payload["thinking"] = {"type": "disabled"}

headers = {"Content-Type": "application/json"}
headers.update(auth_headers)

req = urllib.request.Request(
    url,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers=headers,
    method="POST",
)

with urllib.request.urlopen(req, timeout=15) as resp:
    raw = resp.read().decode("utf-8")
    print(f"Raw: {raw}")
    data = json.loads(raw)

content = data["choices"][0]["message"]["content"].strip()
print(f"Content: '{content}'")
