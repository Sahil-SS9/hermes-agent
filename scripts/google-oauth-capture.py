#!/usr/bin/env python3
"""Google Workspace OAuth re-auth helper for Hermes Agent.

Usage:
  python3 /home/kensei/.hermes/scripts/google-oauth-capture.py <email>

Starts a lightweight localhost:8000 callback server, prints an auth URL,
exchanges the code for tokens, and writes the credential file atomically
to ~/.google_workspace_mcp/credentials/<email>.json.

Requires the gateway to be stopped (so port 8000 is free).
"""
import base64
import hashlib
import html
import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

EXPECTED_EMAIL = sys.argv[1] if len(sys.argv) > 1 else None
REDIRECT_URI = "http://localhost:8000/oauth2callback"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
USERINFO_URI = "https://www.googleapis.com/oauth2/v1/userinfo"
CREDS_DIR = Path.home() / ".google_workspace_mcp" / "credentials"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/presentations.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.body.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/script.projects.readonly",
    "https://www.googleapis.com/auth/script.deployments.readonly",
    "https://www.googleapis.com/auth/script.metrics",
    "https://www.googleapis.com/auth/script.processes",
    "https://www.googleapis.com/auth/cse",
]


def load_oauth_client():
    """Load OAuth client ID/secret from Hermes config (inline or env vars).

    NOTE: secret currently lives in config.yaml plaintext per outstanding
    security-debt; will be migrated to .env as part of the credential rotation
    stage. The file is mode 600 inside ~/.hermes/ (mode 700), so it's user-
    scoped, but not preferred long-term.
    """
    try:
        import yaml
        cfg_path = Path.home() / ".hermes" / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        env = (((cfg.get("mcp_servers") or {}).get("google_workspace") or {}).get("env") or {})
    except Exception:
        env = {}
    client_id = env.get("GOOGLE_OAUTH_CLIENT_ID") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = env.get("GOOGLE_OAUTH_CLIENT_SECRET") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("Missing Google OAuth client ID/secret in ~/.hermes/config.yaml")
    return client_id, client_secret


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def atomic_write(path: Path, data: dict):
    """Write credential file atomically (write .tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(str(tmp), str(path))
    return path


def main():
    client_id, client_secret = load_oauth_client()
    state = secrets.token_urlsafe(24)
    code_verifier = b64url(secrets.token_bytes(64))
    code_challenge = b64url(hashlib.sha256(code_verifier.encode()).digest())
    done = threading.Event()
    result = {"ok": False}

    class ReuseHTTPServer(HTTPServer):
        allow_reuse_address = True
        allow_reuse_port = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/oauth2callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("state", [None])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid OAuth state. Close this tab and retry.")
                result.update({"ok": False, "error": "invalid_state"})
                done.set()
                return
            code = qs.get("code", [None])[0]
            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing OAuth code. Close this tab and retry.")
                result.update({"ok": False, "error": "missing_code"})
                done.set()
                return

            try:
                import requests as rq
                token_resp = rq.post(
                    TOKEN_URI,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "code_verifier": code_verifier,
                        "grant_type": "authorization_code",
                        "redirect_uri": REDIRECT_URI,
                    },
                    timeout=20,
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()
                access_token = token_data["access_token"]

                userinfo = rq.get(
                    USERINFO_URI,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=20,
                )
                userinfo.raise_for_status()
                email = userinfo.json()["email"]

                cred = {
                    "token": access_token,
                    "refresh_token": token_data.get("refresh_token"),
                    "token_uri": TOKEN_URI,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scopes": list(SCOPES),
                    "universe_domain": "googleapis.com",
                    "account": email,
                }
                if not cred["refresh_token"]:
                    raise RuntimeError(
                        "No refresh_token returned. Revoke app access for this account in Google "
                        "Security settings, then retry with prompt=consent."
                    )

                path = atomic_write(CREDS_DIR / f"{email}.json", cred)
                result.update({
                    "ok": True,
                    "email": email,
                    "path": str(path),
                    "expected": EXPECTED_EMAIL,
                })

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                safe_email = html.escape(email, quote=True)
                body = (
                    f"<html><body style=\"font-family:sans-serif;text-align:"
                    f"center;margin-top:20vh\">"
                    f"<h2>Authenticated {safe_email}</h2>"
                    f"<p>Credential saved. You can close this tab.</p></body></html>"
                )
                self.wfile.write(body.encode())
            except Exception as exc:
                # Log full traceback to stderr (visible to operator); send a generic message in the HTTP body
                traceback.print_exc(file=sys.stderr)
                result.update({"ok": False, "error": type(exc).__name__})
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"OAuth flow failed. Check server logs for details.")
            finally:
                done.set()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if EXPECTED_EMAIL:
        params["login_hint"] = EXPECTED_EMAIL
    auth_url = AUTH_URI + "?" + urllib.parse.urlencode(params)

    print("AUTH_URL_START")
    print(auth_url)
    print("AUTH_URL_END")
    print(f"Waiting for callback on {REDIRECT_URI} for expected={EXPECTED_EMAIL or 'any'}",
          flush=True)

    server = ReuseHTTPServer(("127.0.0.1", 8000), Handler)
    server.timeout = 1
    deadline = time.time() + 900  # 15 minutes
    while time.time() < deadline and not done.is_set():
        server.handle_request()
    server.server_close()

    print("RESULT_START")
    print(json.dumps(result, indent=2))
    print("RESULT_END")
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
