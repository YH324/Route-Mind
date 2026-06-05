import urllib.request, json, sys

from config import MIMO_API_KEY, MIMO_CHAT_URL, MIMO_MODEL

payload = {
    "model": MIMO_MODEL,
    "messages": [
        {"role": "system", "content": "你是一个旅游意图分类助手。"},
        {"role": "user", "content": "用户说：想吃火锅。请判断这是 single_poi（只想去一个地方）、simple_route（简单逛2-3个地方）还是 complex_route（完整路线规划）。只输出 JSON：{\"intent_type\":\"...\"}"}
    ],
    "max_completion_tokens": 200,
    "temperature": 0.1,
    "stream": False,
    "thinking": {"type": "disabled"}
}

if not MIMO_API_KEY:
    print("Error: MIMO_API_KEY is not configured.")
    sys.exit(1)

req = urllib.request.Request(
    MIMO_CHAT_URL,
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={
        "api-key": MIMO_API_KEY,
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    print("Status: OK")
    print(data["choices"][0]["message"]["content"])
except Exception as e:
    print(f"Error: {e}")
