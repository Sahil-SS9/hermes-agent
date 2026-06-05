#!/usr/bin/env python3
"""
Selective Tor proxy: routes only opencode.ai traffic through Tor (rotating IPs).
Everything else passes direct.  Listens as an HTTP(S) forward proxy.

Usage:
  export HTTP_PROXY=http://127.0.0.1:8118
  export HTTPS_PROXY=http://127.0.0.1:8118
  export NO_PROXY=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8

  # Force a new IP:
  python3 /home/kensei/.hermes/scripts/selective-tor-proxy.py --new-ip

Limitations:
  - SOCKS5 only (Tor default). Handles HTTP/HTTPS/WS/WSS.
  - No caching, no auth, no logging by default.
  - IPv6 targets not supported through Tor.
"""

import asyncio
import logging
import os
import socket
import struct
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tproxy")

TOR_SOCKS = ("127.0.0.1", 9050)
TOR_CONTROL = ("127.0.0.1", 9051)
TOR_COOKIE = Path("/run/tor/control.authcookie")
LISTEN = ("127.0.0.1", 8118)

# Domains to route through Tor (lowercase comparison)
TOR_ROUTES = {
    "opencode.ai",
    "*.opencode.ai",
}

TARGET = "opencode.ai"

# ── SOCKS5 helpers ──────────────────────────────────────────────────────────

SOCKS5_ATYP_IPV4 = 1
SOCKS5_ATYP_DOMAIN = 3
SOCKS5_ATYP_IPV6 = 4


async def socks5_connect(host: str, port: int) -> tuple | None:
    """Open a TCP connection through Tor's SOCKS5 proxy. Returns (reader, writer) or None."""
    try:
        r, w = await asyncio.open_connection(
            TOR_SOCKS[0], TOR_SOCKS[1], family=socket.AF_INET
        )
        # Greeting: no auth
        w.write(b"\x05\x01\x00")
        await w.drain()
        buf = await r.readexactly(2)
        if buf[0] != 5 or buf[1] != 0:
            log.error("SOCKS5 greeting rejected: %r", buf)
            w.close()
            return None
        # Connect request
        host_bytes = host.encode("ascii")
        msg = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", port)
        w.write(msg)
        await w.drain()
        buf = await r.readexactly(4)
        if buf[1] != 0:
            log.error("SOCKS5 connect rejected: status=%d", buf[1])
            w.close()
            return None
        # Skip remaining response (BND.ADDR + BND.PORT)
        atyp = buf[3]
        if atyp == SOCKS5_ATYP_IPV4:
            await r.readexactly(6)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            dlen = (await r.readexactly(1))[0]
            await r.readexactly(dlen + 2)
        elif atyp == SOCKS5_ATYP_IPV6:
            await r.readexactly(18)
        else:
            log.error("unknown SOCKS5 atyp %d", atyp)
            w.close()
            return None
        return (r, w)
    except Exception as e:
        log.error("SOCKS5 error to %s:%s: %s", host, port, e)
        return None


async def direct_connect(host: str, port: int) -> tuple | None:
    """Open a direct TCP connection."""
    try:
        r, w = await asyncio.open_connection(host, port, family=socket.AF_INET)
        return (r, w)
    except Exception as e:
        log.warning("Direct connect failed to %s:%s: %s", host, port, e)
        return None


def should_route_via_tor(host: str) -> bool:
    """Check if a hostname should go through Tor."""
    host = host.strip().lower()
    if host == TARGET:
        return True
    if host.endswith("." + TARGET):
        return True
    return False


# ── HTTP CONNECT tunnel (for HTTPS targets) ───────────────────────────────


async def tunnel(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter,
                 target_host: str, target_port: int, use_tor: bool):
    """Establish tunnel to target and relay bidirectional data."""
    remote = await (socks5_connect(target_host, target_port) if use_tor
                    else direct_connect(target_host, target_port))
    if remote is None:
        client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        await client_w.drain()
        return
    remote_r, remote_w = remote

    client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await client_w.drain()

    via = "Tor" if use_tor else "direct"
    log.info("Tunnel %s → %s:%s (%s)", client_w.get_extra_info('peername'),
             target_host, target_port, via)

    # Bidirectional relay
    async def relay(src_r: asyncio.StreamReader, dst_w: asyncio.StreamWriter, name: str):
        try:
            while True:
                data = await src_r.read(65536)
                if not data:
                    break
                dst_w.write(data)
                await dst_w.drain()
        except Exception:
            pass
        finally:
            try:
                dst_w.close()
            except Exception:
                pass

    await asyncio.gather(
        relay(client_r, remote_w, "C→R"),
        relay(remote_r, client_w, "C←R"),
    )


# ── HTTP forward proxy (for plain HTTP) ───────────────────────────────────


async def handle_http_request(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter,
                              method: bytes, path: bytes, headers: list,
                              target_host: str, target_port: int, use_tor: bool):
    """Handle a plain HTTP proxy request by forwarding through Tor or direct."""
    remote = await (socks5_connect(target_host, target_port) if use_tor
                    else direct_connect(target_host, target_port))
    if remote is None:
        client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        await client_w.drain()
        return
    remote_r, remote_w = remote

    via = "Tor" if use_tor else "direct"
    log.info("HTTP %s %s:%s (%s)", method.decode(), target_host, target_port, via)

    # Reconstruct the request (strip proxy info from path)
    if path.startswith(b"http://"):
        # Full URL - strip to just path
        path = b"/" + path.split(b"/", 3)[-1:][0] if b"/" in path.split(b"://", 1)[1] else b"/"

    req_line = method + b" " + path + b" HTTP/1.1\r\n"
    remote_w.write(req_line)
    for hdr in headers:
        remote_w.write(hdr + b"\r\n")
    remote_w.write(b"\r\n")

    # Relay request body
    content_length = 0
    for hdr in headers:
        if hdr.lower().startswith(b"content-length:"):
            try:
                content_length = int(hdr.split(b":")[1].strip())
            except ValueError:
                pass
            break
    if content_length > 0:
        body = await client_r.readexactly(content_length)
        remote_w.write(body)
    await remote_w.drain()

    # Read response status line
    status_line = await remote_r.readline()
    
    # Auto-rotate Tor IP on 429 from opencode.ai
    if use_tor and b"429" in status_line:
        log.warning("429 from opencode.ai — rotating Tor IP...")
        asyncio.ensure_future(_rotate_and_notify())

    # Relay response: status line + headers
    client_w.write(status_line)
    while True:
        hdr = await remote_r.readline()
        client_w.write(hdr)
        if hdr in (b"\r\n", b"\n", b""):
            break
    await client_w.drain()

    # Relay response body
    while True:
        data = await remote_r.read(65536)
        if not data:
            break
        client_w.write(data)
        await client_w.drain()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _rotate_and_notify():
    """Rotate Tor exit IP and log the result."""
    ok = await new_tor_ip()
    if ok:
        log.info("Tor IP rotated after 429")
        _clear_zen_pool()
    else:
        log.warning("Tor IP rotation failed after 429")


def _clear_zen_pool():
    """Clear exhausted status on opencode-zen pool entries so next request retries."""
    import json
    path = Path.home() / ".hermes" / "auth.json"
    try:
        data = json.loads(path.read_text())
        pool = data.get("credential_pool", {}).get("opencode-zen")
        if not pool:
            return
        changed = False
        for entry in pool:
            if entry.get("last_status") == "exhausted":
                entry["last_status"] = None
                entry["last_status_at"] = None
                entry["last_error_code"] = None
                entry["last_error_reason"] = None
                entry["last_error_message"] = None
                entry["last_error_reset_at"] = None
                changed = True
        if changed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            log.info("Cleared exhausted status on %d opencode-zen pool entries", len(pool))
    except Exception as e:
        log.warning("Failed to clear Zen pool: %s", e)


# ── Client handler ─────────────────────────────────────────────────────────


async def handle_client(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter):
    """Parse the first line and decide routing."""
    try:
        request_line = await asyncio.wait_for(client_r.readline(), timeout=30)
    except asyncio.TimeoutError:
        return

    if not request_line:
        return

    parts = request_line.strip().split(b" ", 2)
    if len(parts) < 2:
        return

    method = parts[0]
    target = parts[1]

    # Gather headers
    headers = []
    while True:
        try:
            line = await asyncio.wait_for(client_r.readline(), timeout=10)
        except asyncio.TimeoutError:
            break
        if line in (b"\r\n", b"\n", b""):
            break
        headers.append(line.strip())

    # Parse target host and port
    if method == b"CONNECT":
        # CONNECT hostname:port HTTP/1.1
        hostport = target.decode("ascii")
        if ":" in hostport:
            host, _, port_str = hostport.rpartition(":")
            port = int(port_str)
        else:
            host = hostport
            port = 443
    else:
        # GET http://hostname:port/path HTTP/1.1
        target_str = target.decode("ascii")
        if target_str.startswith("http://") or target_str.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(target_str)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        else:
            host = target_str  # relative path, use Host header
            port = 80
            # Try to get host from Host header
            for hdr in headers:
                if hdr.lower().startswith(b"host:"):
                    host_val = hdr.split(b":", 1)[1].strip().decode("ascii")
                    if ":" in host_val:
                        host, _, port_str = host_val.rpartition(":")
                        port = int(port_str)
                    else:
                        host = host_val
                    break

    if not host:
        client_w.close()
        return

    use_tor = should_route_via_tor(host)

    if method == b"CONNECT":
        await tunnel(client_r, client_w, host, port, use_tor)
    else:
        await handle_http_request(client_r, client_w, method, target, headers, host, port, use_tor)


# ── NEWNYM circuit rotation ────────────────────────────────────────────────


async def new_tor_ip(timeout: float = 15.0) -> bool:
    """Send NEWNYM signal to Tor control port to get a fresh exit IP.
    Delegates to the rotate-tor-ip.sh script which handles cookie auth."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sh", str(Path(__file__).parent / "rotate-tor-ip.sh"),
            "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            log.info("NEWNYM sent: new Tor circuit established")
            return True
        log.error("NEWNYM failed (exit=%d): %s", proc.returncode, stderr.decode().strip())
        return False
    except asyncio.TimeoutError:
        log.error("NEWNYM timed out")
        return False
    except Exception as e:
        log.error("NEWNYM error: %s", e)
        return False


# ── Main ────────────────────────────────────────────────────────────────────


async def main():
    if "--new-ip" in sys.argv or "-n" in sys.argv:
        ok = await new_tor_ip()
        sys.exit(0 if ok else 1)

    server = await asyncio.start_server(handle_client, LISTEN[0], LISTEN[1],
                                        family=socket.AF_INET)
    log.info("Selective Tor proxy listening on %s:%s", LISTEN[0], LISTEN[1])
    log.info("Routing: %s → Tor, everything else → direct", TARGET)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())