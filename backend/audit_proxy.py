"""Minimal authenticated HTTP proxy for Codex audit workers."""

from __future__ import annotations

import base64
import http.client
import os
import select
import socket
import socketserver
from http.server import BaseHTTPRequestHandler
from typing import Iterable
from urllib.parse import urlparse

from app.services.gap_taxonomy import registrable_domain
from app.services.internal_audit_auth import InternalAuditAuthError, verify_job_token


def _allowed_host(host: str, claims: dict) -> bool:
    normalized = str(host or "").lower().strip(".")
    if not normalized:
        return False
    if normalized in {str(item).lower() for item in (claims.get("allowed_internal_hosts") or [])}:
        return True
    return registrable_domain(normalized) == str(claims.get("target_registrable_domain") or "")


def _decode_proxy_token(header_value: str) -> str:
    if not header_value.startswith("Basic "):
        raise InternalAuditAuthError("Proxy authentication is required.")
    raw = base64.b64decode(header_value[6:].strip()).decode("utf-8")
    _, _, token = raw.partition(":")
    if not token:
        raise InternalAuditAuthError("Proxy token is missing.")
    return token


class AuditProxyHandler(BaseHTTPRequestHandler):
    timeout = 30
    protocol_version = "HTTP/1.1"

    def _claims(self) -> dict:
        token = _decode_proxy_token(self.headers.get("Proxy-Authorization", ""))
        return verify_job_token(token, audience="audit_proxy")

    def _deny(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self) -> None:
        try:
            claims = self._claims()
        except InternalAuditAuthError as exc:
            self._deny(407, str(exc))
            return

        host, _, port_text = self.path.partition(":")
        port = int(port_text or "443")
        if port not in {80, 443} or not _allowed_host(host, claims):
            self._deny(403, f"Denied destination: {host}:{port}")
            return

        upstream = socket.create_connection((host, port), timeout=self.timeout)
        self.send_response(200, "Connection Established")
        self.end_headers()
        self.connection.setblocking(False)
        upstream.setblocking(False)
        sockets: Iterable[socket.socket] = (self.connection, upstream)
        try:
            while True:
                readable, _, exceptional = select.select(list(sockets), [], list(sockets), self.timeout)
                if exceptional:
                    break
                if not readable:
                    break
                for sock in readable:
                    other = upstream if sock is self.connection else self.connection
                    data = sock.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        finally:
            upstream.close()

    def _forward_http(self) -> None:
        try:
            claims = self._claims()
        except InternalAuditAuthError as exc:
            self._deny(407, str(exc))
            return

        target = urlparse(self.path)
        if target.scheme not in {"http", "https"} or not _allowed_host(target.hostname or "", claims):
            self._deny(403, f"Denied destination: {self.path}")
            return

        body = None
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            body = self.rfile.read(length)

        connection_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        conn = connection_cls(target.hostname, target.port, timeout=self.timeout)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"proxy-authorization", "proxy-connection", "connection", "host"}
        }
        headers["Host"] = target.netloc
        path = target.path or "/"
        if target.query:
            path = f"{path}?{target.query}"
        conn.request(self.command, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() in {"transfer-encoding", "connection", "proxy-connection"}:
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        conn.close()

    def do_GET(self) -> None:  # noqa: N802
        self._forward_http()

    def do_POST(self) -> None:  # noqa: N802
        self._forward_http()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward_http()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward_http()

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward_http()


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    host = os.environ.get("OPENINGRESS_AUDIT_PROXY_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENINGRESS_AUDIT_PROXY_PORT", "8877"))
    with ThreadingTCPServer((host, port), AuditProxyHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
