"""
RouteMind Web Server

工业级改进：
1. API v2 标准化信封格式 (code/msg/request_id/data)
2. OpenAPI 3.0 文档端点
3. 运行时指标端点
4. 结构化日志支持
5. 增强健康检查（依赖状态）
6. v1/v2 双格式兼容
"""
import json
import logging
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver

class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
from urllib.parse import parse_qs, urlparse

from app_service import run_agent
from config import (
    ENABLE_CORS, LOG_LEVEL, MAX_REQUEST_BYTES, SERVER_HOST, SERVER_PORT,
    REQUEST_TIMEOUT_SECONDS, SERVER_VERSION, WARMUP_ON_START, LOG_FORMAT,
)
from data_repository import RepositoryError, repository
from interaction_intelligence import interaction_manager, normalize_id


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
FEATURES = [
    "semantic_search", "road_network", "llm_intent", "business_hours",
    "type_diversity", "session_memory", "dialogue_state", "need_matching",
    "api_v2", "openapi", "metrics", "structured_logs",
]

# ---------- Logging Setup ----------
_log_format = os.environ.get("LOG_FORMAT", LOG_FORMAT or "text").lower()
if _log_format == "json":
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
    )
else:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
logger = logging.getLogger("route-planner")


# ---------- Metrics ----------
class MetricsCollector:
    """简易运行时指标收集器。生产环境可替换为 Prometheus client."""

    def __init__(self):
        self._requests = 0
        self._errors = 0
        self._total_latency_ms = 0
        self._started_at = time.time()

    def record(self, latency_ms, is_error=False):
        self._requests += 1
        self._total_latency_ms += latency_ms
        if is_error:
            self._errors += 1

    @property
    def summary(self):
        uptime = time.time() - self._started_at
        return {
            "requests_total": self._requests,
            "errors_total": self._errors,
            "avg_latency_ms": round(self._total_latency_ms / max(self._requests, 1), 2),
            "uptime_s": round(uptime, 1),
            "rps": round(self._requests / max(uptime, 1), 3),
        }


metrics = MetricsCollector()


# ---------- OpenAPI Spec ----------
OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "RouteMind API",
        "description": "智能路线规划系统 API。支持自然语言目标输入，输出多方案路线规划。",
        "version": SERVER_VERSION,
        "contact": {"name": "RouteMind Team"},
    },
    "servers": [{"url": "/api", "description": "当前服务器"}],
    "paths": {
        "/plan": {
            "post": {
                "summary": "路线规划（v1 兼容格式）",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "goal": {"type": "string", "description": "自然语言目标"},
                                    "radius": {"type": "integer", "default": 3000},
                                    "user_mode": {"type": "string", "enum": ["tourist", "business", "resident"], "default": "tourist"},
                                    "session_id": {"type": "string"},
                                    "user_id": {"type": "string"},
                                    "dialogue": {"type": "array"},
                                    "center_lat": {"type": "number"},
                                    "center_lng": {"type": "number"},
                                    "city": {"type": "string", "default": "chengdu"},
                                },
                                "required": ["goal"],
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "规划结果",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "ok": {"type": "boolean"},
                                        "result": {"type": "object"},
                                        "performance": {"type": "object"},
                                        "request_id": {"type": "string"},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/v2/plan": {
            "post": {
                "summary": "路线规划（v2 标准信封）",
                "requestBody": {"$ref": "#/paths/~1plan/post/requestBody"},
                "responses": {
                    "200": {
                        "description": "标准信封格式响应",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "code": {"type": "integer"},
                                        "msg": {"type": "string"},
                                        "request_id": {"type": "string"},
                                        "data": {"type": "object"},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/health": {
            "get": {
                "summary": "健康检查",
                "responses": {
                    "200": {
                        "description": "服务健康状态",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "ok": {"type": "boolean"},
                                        "version": {"type": "string"},
                                        "features": {"type": "array", "items": {"type": "string"}},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/ready": {
            "get": {
                "summary": "就绪检查",
                "responses": {
                    "200": {"description": "服务就绪"},
                    "503": {"description": "服务未就绪"},
                }
            }
        },
        "/metrics": {
            "get": {
                "summary": "运行时指标",
                "responses": {
                    "200": {
                        "description": "指标数据",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    }
                }
            }
        },
        "/session": {
            "get": {"summary": "查询会话状态", "responses": {"200": {"description": "会话状态"}}},
        },
        "/session/clear": {
            "post": {"summary": "清除会话记忆", "responses": {"200": {"description": "清除结果"}}},
        },
        "/profile": {
            "get": {"summary": "查询用户画像", "responses": {"200": {"description": "画像数据"}}},
        },
        "/profile/clear": {
            "post": {"summary": "清除用户画像", "responses": {"200": {"description": "清除结果"}}},
        },
        "/feedback": {
            "post": {"summary": "提交反馈", "responses": {"200": {"description": "反馈结果"}}},
        },
    },
}


# ---------- Helpers ----------
def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _to_v2_envelope(v1_response, request_id):
    """将 v1 响应转换为 v2 标准信封格式。"""
    if not isinstance(v1_response, dict):
        return {"code": 500, "msg": "Internal error", "request_id": request_id, "data": None}

    if v1_response.get("ok"):
        return {
            "code": 200,
            "msg": "success",
            "request_id": request_id,
            "data": {k: v for k, v in v1_response.items() if k not in ("ok", "request_id")},
        }
    else:
        return {
            "code": _error_code_to_http(v1_response.get("error_code")),
            "msg": v1_response.get("error", "Unknown error"),
            "request_id": request_id,
            "error_code": v1_response.get("error_code"),
            "data": None,
        }


def _error_code_to_http(error_code):
    mapping = {
        "INVALID_PAYLOAD": 400,
        "EMPTY_GOAL": 400,
        "GOAL_TOO_LONG": 400,
        "UNSUPPORTED_SERVICE_AREA": 422,
        "NO_POI": 404,
        "DATA_NOT_READY": 503,
        "DATA_FILE_MISSING": 503,
        "DATA_FILE_INVALID": 503,
        "REQUEST_TOO_LARGE": 413,
        "INVALID_JSON": 400,
        "HANDLER_ERROR": 500,
        "INTERNAL_ERROR": 500,
        "NOT_FOUND": 404,
        "MISSING_USER_ID": 400,
        "INVALID_FEEDBACK": 400,
    }
    return mapping.get(error_code, 500)


def _check_llm_ready():
    """检查至少一个 LLM provider 可用。"""
    from config import MIMO_API_KEY, MINIMAX_API_KEY, GLM_API_KEY
    return bool(MIMO_API_KEY or MINIMAX_API_KEY or GLM_API_KEY)


# ---------- Handler ----------
class RoutePlannerHandler(BaseHTTPRequestHandler):
    server_version = "RouteMind/{}".format(SERVER_VERSION)

    def _request_id(self):
        request_id = self.headers.get("X-Request-Id", "").strip()
        return request_id or uuid.uuid4().hex

    def _is_v2(self):
        """判断是否请求 v2 格式：URL 以 /v2/ 开头，或 header 包含 X-API-Version: 2。"""
        path = urlparse(self.path).path
        if path.startswith("/api/v2/"):
            return True
        return self.headers.get("X-API-Version", "").strip() == "2"

    def _send_headers(self, content_type, length, status, request_id=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(length))
        if request_id:
            self.send_header("X-Request-Id", request_id)
        if ENABLE_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-Id, X-API-Version")
        self.end_headers()

    def _send_json(self, payload, status=200):
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_headers("application/json", len(body), status, request_id)
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self._send_headers("text/html", len(body), status)
        self.wfile.write(body)

    def _send_text(self, text, content_type, status=200):
        body = text.encode("utf-8")
        self._send_headers(content_type, len(body), status)
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_headers("text/plain", 0, 204)

    def do_GET(self):
        path = urlparse(self.path).path

        # Static files
        if path in ("/", "/index.html"):
            self._send_html(_read_text(os.path.join(WEB_DIR, "index.html")))
            return
        if path == "/app.js":
            self._send_text(_read_text(os.path.join(WEB_DIR, "app.js")), "application/javascript")
            return
        if path == "/styles.css":
            self._send_text(_read_text(os.path.join(WEB_DIR, "styles.css")), "text/css")
            return

        # API endpoints
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "version": SERVER_VERSION,
                "python": sys.version.split()[0],
                "features": FEATURES,
                "dependencies": {
                    "data_ready": repository.status()["ready"],
                    "llm_available": _check_llm_ready(),
                },
            })
            return

        if path == "/api/ready":
            status = repository.status()
            self._send_json({
                "ok": status["ready"],
                "version": SERVER_VERSION,
                "data": status,
            }, status=200 if status["ready"] else 503)
            return

        if path == "/api/metrics":
            self._send_json({
                "ok": True,
                "version": SERVER_VERSION,
                "metrics": metrics.summary,
            })
            return

        if path == "/api/openapi.json":
            self._send_json({"ok": True, "openapi": OPENAPI_SPEC})
            return

        if path == "/api/session":
            query = parse_qs(urlparse(self.path).query)
            session_id = normalize_id((query.get("session_id") or ["default-session"])[0], "default-session")
            user_id = normalize_id((query.get("user_id") or [""])[0])
            self._send_json({
                "ok": True,
                "session": interaction_manager.session_status(session_id),
                "profile": interaction_manager.profile_status(user_id) if user_id else {},
                "persistence": interaction_manager.memory.persistence_status(),
            })
            return

        if path == "/api/profile":
            query = parse_qs(urlparse(self.path).query)
            user_id = normalize_id((query.get("user_id") or [""])[0])
            self._send_json({
                "ok": bool(user_id),
                "profile": interaction_manager.profile_status(user_id) if user_id else {},
                "persistence": interaction_manager.memory.persistence_status(),
                "error_code": None if user_id else "MISSING_USER_ID",
            }, status=200 if user_id else 400)
            return

        self._send_json({"ok": False, "error": "Not found", "error_code": "NOT_FOUND"}, status=404)

    def do_POST(self):
        request_id = self._request_id()
        started = time.time()
        path = urlparse(self.path).path
        is_v2 = self._is_v2()

        # Handle non-plan POST endpoints
        if path in ("/api/session/clear", "/api/profile/clear", "/api/feedback"):
            self._handle_post_command(path, request_id, is_v2)
            return

        # Plan endpoints
        if path not in ("/api/plan", "/api/v2/plan"):
            self._send_json({"ok": False, "request_id": request_id, "error": "Not found", "error_code": "NOT_FOUND"}, status=404)
            return

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length > MAX_REQUEST_BYTES:
            resp = {"ok": False, "request_id": request_id, "error": "请求体过大", "error_code": "REQUEST_TOO_LARGE"}
            self._respond_plan(resp, request_id, is_v2, started, path)
            return

        raw = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            resp = {"ok": False, "request_id": request_id, "error": "Invalid JSON", "error_code": "INVALID_JSON"}
            self._respond_plan(resp, request_id, is_v2, started, path)
            return

        try:
            response = run_agent(payload, request_id=request_id)
        except Exception as exc:
            logger.exception("request_id=%s unexpected handler error", request_id)
            resp = {"ok": False, "request_id": request_id, "error": str(exc), "error_code": "HANDLER_ERROR"}
            self._respond_plan(resp, request_id, is_v2, started, path)
            return

        self._respond_plan(response, request_id, is_v2, started, path)

    def _handle_post_command(self, path, request_id, is_v2):
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            self._respond_command({"ok": False, "request_id": request_id, "error": "Invalid JSON", "error_code": "INVALID_JSON"}, request_id, is_v2)
            return

        if path == "/api/feedback":
            applied = interaction_manager.apply_feedback(payload)
            user_id = normalize_id(payload.get("user_id"))
            self._respond_command({
                "ok": applied,
                "request_id": request_id,
                "profile": interaction_manager.profile_status(user_id) if user_id else {},
                "error_code": None if applied else "INVALID_FEEDBACK",
            }, request_id, is_v2, status=200 if applied else 400)
            return

        if path == "/api/profile/clear":
            user_id = normalize_id(payload.get("user_id"))
            cleared = interaction_manager.clear_profile(user_id) if user_id else False
            self._respond_command({"ok": bool(user_id), "request_id": request_id, "cleared": cleared, "user_id": user_id}, request_id, is_v2, status=200 if user_id else 400)
            return

        session_id = normalize_id(payload.get("session_id"), "default-session")
        cleared = interaction_manager.clear_session(session_id)
        self._respond_command({"ok": True, "request_id": request_id, "cleared": cleared, "session_id": session_id}, request_id, is_v2)

    def _respond_plan(self, v1_response, request_id, is_v2, started, path):
        elapsed_ms = round((time.time() - started) * 1000)
        is_error = not v1_response.get("ok")
        metrics.record(elapsed_ms, is_error)

        logger.info(
            "request_id=%s path=%s ok=%s elapsed_ms=%s intent=%s v2=%s",
            request_id,
            path,
            v1_response.get("ok"),
            elapsed_ms,
            v1_response.get("result", {}).get("constraints", {}).get("intent_type"),
            is_v2,
        )

        if is_v2:
            envelope = _to_v2_envelope(v1_response, request_id)
            status = envelope.get("code", 200)
            self._send_json(envelope, status=status)
        else:
            self._send_json(v1_response)

    def _respond_command(self, v1_response, request_id, is_v2, status=200):
        if is_v2:
            envelope = _to_v2_envelope(v1_response, request_id)
            status = envelope.get("code", status)
            self._send_json(envelope, status=status)
        else:
            self._send_json(v1_response, status=status)

    def log_message(self, format_string, *args):
        logger.debug("%s - %s", self.address_string(), format_string % args)


# ---------- Server ----------
def serve(host="127.0.0.1", port=8000):
    if WARMUP_ON_START:
        try:
            warmup_ms = repository.warmup()
            logger.info("data warmup completed warmup_ms=%s", warmup_ms)
        except RepositoryError as exc:
            logger.error("data warmup failed: %s", exc)

    # Print config summary (sensitive keys masked)
    from config import MIMO_API_KEY, MINIMAX_API_KEY, GLM_API_KEY
    logger.info("RouteMind %s starting on http://%s:%s", SERVER_VERSION, host, port)
    logger.info("features=%s log_format=%s cors=%s", FEATURES, _log_format, ENABLE_CORS)
    logger.info("llm_providers: mimo=%s minimax=%s glm=%s",
                bool(MIMO_API_KEY), bool(MINIMAX_API_KEY), bool(GLM_API_KEY))

    server = ThreadingHTTPServer((host, int(port)), RoutePlannerHandler)
    server.daemon_threads = True
    server.timeout = REQUEST_TIMEOUT_SECONDS
    logger.info("serving route planner on http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start the route planner web server.")
    parser.add_argument("--host", default=SERVER_HOST, help="Bind host.")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Bind port.")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
