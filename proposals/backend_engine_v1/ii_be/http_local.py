"""Servidor HTTP LOCAL opcional para a API (testes e uso futuro pelo painel). Nunca exposto à rede.

- Escuta só em loopback (127.0.0.1 ou ::1); qualquer outro endereço é recusado na criação.
- Confere o cabeçalho Host (127.0.0.1/localhost/[::1]) contra DNS rebinding.
- `POST /v1/<operação>` com `Content-Type: application/json` (pedido de outra origem no navegador exigiria
  preflight CORS, que este servidor não responde: mitiga CSRF). `GET /v1/health`.
- Corpo limitado a 256 KiB; erros no mesmo envelope da API; sem cabeçalhos CORS.
- Nenhuma porta é aberta no Windows por este pacote: o servidor só existe se alguém chamar `make_server`.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Tuple

from .api import API_VERSION, MAX_BODY_BYTES, ApiError, ServiceAPI

LOOPBACK = ("127.0.0.1", "::1", "localhost")


def make_server(api: ServiceAPI, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise ValueError("o servidor local só escuta em loopback (127.0.0.1/::1)")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ii_be"
        sys_version = ""

        def log_message(self, fmt, *args):  # sem log de requisição no stderr (pode conter dados)
            return

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _error(self, exc: ApiError) -> None:
            self._send(exc.http_status, {"api": API_VERSION, "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}})

        def _host_ok(self) -> bool:
            h = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return h in LOOPBACK

        def do_GET(self):
            if not self._host_ok():
                return self._error(ApiError("VALIDATION_ERROR", "Host não permitido"))
            if self.path == "/v1/health":
                return self._send(200, {"api": API_VERSION, "ok": True, "data": {"status": "ok"}})
            return self._error(ApiError("UNKNOWN_OPERATION", "rota desconhecida"))

        def do_POST(self):
            if not self._host_ok():
                return self._error(ApiError("VALIDATION_ERROR", "Host não permitido"))
            if not self.path.startswith("/v1/") or "?" in self.path:
                return self._error(ApiError("UNKNOWN_OPERATION", "rota desconhecida"))
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._error(ApiError("VALIDATION_ERROR", "Content-Type deve ser application/json"))
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                return self._error(ApiError("VALIDATION_ERROR", "Content-Length inválido"))
            if length > MAX_BODY_BYTES:
                return self._error(ApiError("PAYLOAD_TOO_LARGE", f"corpo maior que {MAX_BODY_BYTES} bytes"))
            body = self.rfile.read(length) if length > 0 else b""
            res = api.handle(self.path[len("/v1/"):], body)
            status = 200 if res.get("ok") else ApiError(res["error"]["code"], "").http_status
            self._send(status, res)

        def do_PUT(self):
            self._error(ApiError("UNKNOWN_OPERATION", "método não suportado"))

        do_DELETE = do_PATCH = do_PUT

    return ThreadingHTTPServer((host, port), Handler)


def serve_in_thread(api: ServiceAPI, host: str = "127.0.0.1", port: int = 0) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    srv = make_server(api, host, port)
    th = threading.Thread(target=srv.serve_forever, name="ii_be-http", daemon=True)
    th.start()
    return srv, th
