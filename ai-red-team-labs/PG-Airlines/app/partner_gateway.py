"""A deliberately fingerprintable partner reverse proxy for the local lab.

This emulates an nginx response surface without adding a full proxy stack.
It must remain bound to loopback through Docker Compose.
"""

import os
import time
import uuid
from wsgiref.simple_server import ServerHandler, WSGIRequestHandler, make_server

import requests
from flask import Flask, Response, jsonify, request


NGINX_VERSION = "nginx/1.26.3"


class NginxServerHandler(ServerHandler):
    http_version = "1.1"


class NginxRequestHandler(WSGIRequestHandler):
    """Make the training service's HTTP Server header match the emulated gateway."""

    protocol_version = "HTTP/1.1"

    def handle(self):
        self.raw_requestline = self.rfile.readline(65537)
        if len(self.raw_requestline) > 65536:
            self.requestline = ""
            self.request_version = ""
            self.command = ""
            self.send_error(414)
            return
        if not self.parse_request():
            return

        handler = NginxServerHandler(
            self.rfile,
            self.wfile,
            self.get_stderr(),
            self.get_environ(),
            multithread=False,
        )
        handler.request_handler = self
        handler.run(self.server.get_app())

    def send_response(self, code, message=None):
        # WSGIRequestHandler normally adds its own Server value. The Flask app
        # supplies the intentionally leaky nginx value instead.
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header("Date", self.date_time_string())


def create_gateway_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        PARTNER_API_KEY=os.getenv("PARTNER_API_KEY", "pgair-partner-demo-only"),
        UPSTREAM_ASSISTANT_URL=os.getenv(
            "UPSTREAM_ASSISTANT_URL", "http://app:5000/api/v2/assistant"
        ),
    )
    if test_config:
        app.config.update(test_config)

    @app.after_request
    def leak_proxy_fingerprint(response):
        # These headers are intentionally verbose so students can identify and
        # fingerprint the reverse proxy during reconnaissance.
        response.headers["Server"] = NGINX_VERSION
        response.headers["RateLimit-Reset"] = "23"
        response.headers["X-RateLimit-Remaining-Minute"] = "59"
        response.headers["X-RateLimit-Limit-Minute"] = "60"
        response.headers["RateLimit-Remaining"] = "59"
        response.headers["RateLimit-Limit"] = "60"
        response.headers["X-Upstream-Response-Time"] = "0.010"
        response.headers["X-Request-Time"] = "0.037"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/v1/auth")
    def auth_info():
        return jsonify(authentication="Bearer token", status="available")

    @app.get("/v1/billing")
    def billing():
        return jsonify(plan="partner-sandbox", status="active")

    @app.route("/v1/chat/completions", methods=["GET", "POST"])
    def chat_completions():
        expected = f"Bearer {app.config['PARTNER_API_KEY']}"
        if request.headers.get("Authorization", "") != expected:
            return Response("Unauthorized\n", status=401, content_type="text/plain; charset=utf-8")
        if request.method != "POST":
            return jsonify(error={"message": "Method not allowed"}), 405

        body = request.get_json(silent=True) or {}
        messages = body.get("messages") or []
        user_messages = [
            item.get("content", "")
            for item in messages
            if isinstance(item, dict) and item.get("role") == "user"
        ]
        message = str(user_messages[-1] if user_messages else body.get("message", "")).strip()
        if not message:
            return jsonify(error={"message": "A user message is required"}), 400

        try:
            upstream = requests.post(
                app.config["UPSTREAM_ASSISTANT_URL"],
                json={"message": message},
                timeout=(5, 180),
            )
            upstream.raise_for_status()
            result = upstream.json()
        except (requests.RequestException, ValueError):
            return jsonify(error={"message": "Bad gateway", "type": "upstream_error"}), 502

        created = int(time.time())
        model = result.get("metadata", {}).get("model", "unknown")
        content = result.get("content", "")
        return jsonify(
            id=f"chatcmpl-{uuid.uuid4().hex[:20]}",
            object="chat.completion",
            created=created,
            model=model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        )

    return app


gateway_app = create_gateway_app()


def main():
    host = os.getenv("PARTNER_GATEWAY_HOST", "0.0.0.0")
    port = int(os.getenv("PARTNER_GATEWAY_PORT", "8000"))
    with make_server(host, port, gateway_app, handler_class=NginxRequestHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
