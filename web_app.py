import json
import logging
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app_service import run_agent
from config import (
    ENABLE_CORS, LOG_LEVEL, MAX_REQUEST_BYTES, SERVER_HOST, SERVER_PORT,
    REQUEST_TIMEOUT_SECONDS, SERVER_VERSION, WARMUP_ON_START,
)
from data_repository import RepositoryError, repository
from interaction_intelligence import interaction_manager, normalize_id


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
FEATURES = [
    "semantic_search", "road_network", "llm_intent", "business_hours",
    "type_diversity", "session_memory", "dialogue_state", "need_matching",
]


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("route-planner")


def _read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "RoutePlanner/{}".format(SERVER_VERSION)

    def _request_id(self):
        request_id = self.headers.get("X-Request-Id", "").strip()
        return request_id or uuid.uuid4().hex

    def _send_headers(self, content_type, length, status, request_id=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(length))
        if request_id:
            self.send_header("X-Request-Id", request_id)
        if ENABLE_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-Id")
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
        if path in ("/", "/index.html"):
            self._send_html(_read_text(os.path.join(WEB_DIR, "index.html")))
            return
        if path == "/app.js":
            self._send_text(_read_text(os.path.join(WEB_DIR, "app.js")), "application/javascript")
            return
        if path == "/styles.css":
            self._send_text(_read_text(os.path.join(WEB_DIR, "styles.css")), "text/css")
            return
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "version": SERVER_VERSION,
                "python": sys.version.split()[0],
                "features": FEATURES,
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
        if path == "/api/session":
            query = parse_qs(urlparse(self.path).query)
            session_id = normalize_id((query.get("session_id") or ["default-session"])[0], "default-session")
            user_id = normalize_id((query.get("user_id") or [""])[0])
            self._send_json({
                "ok": True,
                "session": interaction_manager.session_status(session_id),
                "profile": interaction_manager.profile_status(user_id) if user_id else {},
            })
            return
        if path == "/api/profile":
            query = parse_qs(urlparse(self.path).query)
            user_id = normalize_id((query.get("user_id") or [""])[0])
            self._send_json({
                "ok": bool(user_id),
                "profile": interaction_manager.profile_status(user_id) if user_id else {},
                "error_code": None if user_id else "MISSING_USER_ID",
            }, status=200 if user_id else 400)
            return
        self._send_json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self):
        request_id = self._request_id()
        started = time.time()
        path = urlparse(self.path).path
        if path in ("/api/session/clear", "/api/profile/clear", "/api/feedback"):
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            try:
                payload = json.loads(raw or "{}")
            except ValueError:
                self._send_json({"ok": False, "request_id": request_id, "error": "Invalid JSON", "error_code": "INVALID_JSON"}, status=400)
                return
            if path == "/api/feedback":
                applied = interaction_manager.apply_feedback(payload)
                user_id = normalize_id(payload.get("user_id"))
                self._send_json({
                    "ok": applied,
                    "request_id": request_id,
                    "profile": interaction_manager.profile_status(user_id) if user_id else {},
                    "error_code": None if applied else "INVALID_FEEDBACK",
                }, status=200 if applied else 400)
                return
            if path == "/api/profile/clear":
                user_id = normalize_id(payload.get("user_id"))
                cleared = interaction_manager.clear_profile(user_id) if user_id else False
                self._send_json({"ok": bool(user_id), "request_id": request_id, "cleared": cleared, "user_id": user_id}, status=200 if user_id else 400)
                return
            session_id = normalize_id(payload.get("session_id"), "default-session")
            cleared = interaction_manager.clear_session(session_id)
            self._send_json({"ok": True, "request_id": request_id, "cleared": cleared, "session_id": session_id})
            return

        if path != "/api/plan":
            self._send_json({"ok": False, "request_id": request_id, "error": "Not found", "error_code": "NOT_FOUND"}, status=404)
            return
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length > MAX_REQUEST_BYTES:
            self._send_json({
                "ok": False,
                "request_id": request_id,
                "error": "请求体过大",
                "error_code": "REQUEST_TOO_LARGE",
            }, status=413)
            return
        raw = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            self._send_json({"ok": False, "request_id": request_id, "error": "Invalid JSON", "error_code": "INVALID_JSON"}, status=400)
            return
        try:
            response = run_agent(payload, request_id=request_id)
        except Exception as exc:
            logger.exception("request_id=%s unexpected handler error", request_id)
            self._send_json({"ok": False, "request_id": request_id, "error": str(exc), "error_code": "HANDLER_ERROR"}, status=500)
            return
        elapsed_ms = round((time.time() - started) * 1000)
        logger.info(
            "request_id=%s path=%s ok=%s elapsed_ms=%s intent=%s",
            request_id,
            path,
            response.get("ok"),
            elapsed_ms,
            response.get("result", {}).get("constraints", {}).get("intent_type"),
        )
        self._send_json(response)

    def log_message(self, format_string, *args):
        logger.debug("%s - %s", self.address_string(), format_string % args)


def serve(host="127.0.0.1", port=8000):
    if WARMUP_ON_START:
        try:
            warmup_ms = repository.warmup()
            logger.info("data warmup completed warmup_ms=%s", warmup_ms)
        except RepositoryError as exc:
            logger.error("data warmup failed: %s", exc)
    server = ThreadingHTTPServer((host, int(port)), DemoHandler)
    server.daemon_threads = True
    server.timeout = REQUEST_TIMEOUT_SECONDS
    logger.info("serving route planner on http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Start the route planner web demo.")
    parser.add_argument("--host", default=SERVER_HOST, help="Bind host, default from HOST/HACKATHON_HOST.")
    parser.add_argument("--port", type=int, default=SERVER_PORT, help="Bind port, default from PORT/HACKATHON_PORT.")
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
