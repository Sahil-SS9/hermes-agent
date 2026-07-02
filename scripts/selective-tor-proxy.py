#!/usr/bin/env python3
"""Selective forward proxy — routes target domains through Tor, everything else direct.

Usage:
  python3 selective-tor-proxy.py
  python3 selective-tor-proxy.py --new-ip

Signal-based on-demand rotation (no session restart needed):
  kill -USR1 $(pgrep -f selective-tor-proxy.py)

Runs on 127.0.0.1:8118.
Set HTTPS_PROXY=http://127.0.0.1:8118 in your environment.

Target domain is configured via TOR_ROUTES set (default: opencode.ai).
"""
import asyncio
import json
import logging
import signal
import socket
import struct
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("tproxy")

TOR_SOCKS = ("127.0.0.1", 9050)
LISTEN = ("127.0.0.1", 8118)
TARGET = "opencode.ai"
# Reap a tunnel if neither direction moves a byte for this long. Without it,
# idle keep-alive HTTPS connections pin two sockets each and leak FDs to the limit.
IDLE_TIMEOUT = 120
TOR_ERROR_CODES = (b"429", b"403", b"401")

SOCKS5_ATYP_IPV4 = 1
SOCKS5_ATYP_DOMAIN = 3
SOCKS5_ATYP_IPV6 = 4


def _clear_zen_pool():
    """Clear exhausted status on opencode-zen credential pool entries so next request retries."""
    path = Path.home() / ".hermes" / "auth.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        pool = data.get("credential_pool", {}).get("opencode-zen")
        if not pool:
            return
        cleared = 0
        for entry in pool:
            if entry.get("last_status") == "exhausted":
                entry["last_status"] = None
                entry["last_status_at"] = None
                entry["last_error_code"] = None
                entry["last_error_reason"] = None
                entry["last_error_message"] = None
                entry["last_error_reset_at"] = None
                cleared += 1
        if cleared:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            log.info("Cleared %d exhausted opencode-zen pool entries", cleared)
    except Exception as e:
        log.error("Failed to clear zen pool: %s", e)


async def socks5_connect(host: str, port: int) -> tuple | None:
    try:
        r, w = await asyncio.open_connection(*TOR_SOCKS, family=socket.AF_INET)
        w.write(b"\x05\x01\x00")
        await w.drain()
        buf = await r.readexactly(2)
        if buf[0] != 5 or buf[1] != 0:
            w.close(); return None
        host_bytes = host.encode("ascii")
        msg = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", port)
        w.write(msg)
        await w.drain()
        buf = await r.readexactly(4)
        if buf[1] != 0:
            w.close(); return None
        atyp = buf[3]
        if atyp == SOCKS5_ATYP_IPV4:
            await r.readexactly(6)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            dlen = (await r.readexactly(1))[0]
            await r.readexactly(dlen + 2)
        elif atyp == SOCKS5_ATYP_IPV6:
            await r.readexactly(18)
        else:
            w.close(); return None
        return (r, w)
    except Exception as e:
        log.error("SOCKS5 error %s:%s: %s", host, port, e)
        return None


async def direct_connect(host: str, port: int) -> tuple | None:
    try:
        r, w = await asyncio.open_connection(host, port, family=socket.AF_INET)
        return (r, w)
    except Exception as e:
        log.warning("Direct failed %s:%s: %s", host, port, e)
        return None


def should_route_via_tor(host: str) -> bool:
    host = host.strip().lower()
    return host == TARGET or host.endswith("." + TARGET)


async def _rotate_and_notify():
    """Rotate Tor IP and clear Hermes credential pool exhaustion."""
    ok = await new_tor_ip()
    if ok:
        _clear_zen_pool()
        log.info("Tor IP rotated + credential pool cleared")
    else:
        log.error("Tor rotation failed")


async def new_tor_ip(timeout=15.0) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", str(Path(__file__).parent / "rotate-tor-ip.sh"), "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return True
        log.error("NEWNYM failed (%d): %s", proc.returncode, stderr.decode().strip())
        return False
    except asyncio.TimeoutError:
        log.error("NEWNYM timed out"); return False
    except Exception as e:
        log.error("NEWNYM error: %s", e); return False


async def tunnel(client_r, client_w, target_host, target_port, use_tor):
    remote = await (socks5_connect(target_host, target_port) if use_tor else direct_connect(target_host, target_port))
    if remote is None and use_tor:
        log.warning("Tor unavailable for %s:%s — falling back to direct", target_host, target_port)
        remote = await direct_connect(target_host, target_port)
    if remote is None:
        client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n"); await client_w.drain(); return
    remote_r, remote_w = remote
    client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n"); await client_w.drain()
    log.info("Tunnel %s:%s (%s)", target_host, target_port, "Tor" if use_tor else "direct")

    async def relay(src_r, dst_w):
        try:
            while True:
                d = await asyncio.wait_for(src_r.read(65536), timeout=IDLE_TIMEOUT)
                if not d: break
                dst_w.write(d); await dst_w.drain()
        except Exception:
            pass

    def _close(w):
        try:
            if not w.is_closing(): w.close()
        except Exception:
            pass

    # Run both directions; as soon as one ends (EOF, idle timeout, error),
    # close both sockets so the other side unblocks and no FDs are pinned.
    t1 = asyncio.ensure_future(relay(client_r, remote_w))
    t2 = asyncio.ensure_future(relay(remote_r, client_w))
    try:
        await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        _close(remote_w); _close(client_w)
        for t in (t1, t2):
            if not t.done():
                t.cancel()


async def handle_http(client_r, client_w, method, path, headers, target_host, target_port, use_tor):
    remote = await (socks5_connect(target_host, target_port) if use_tor else direct_connect(target_host, target_port))
    if remote is None and use_tor:
        log.warning("Tor unavailable for %s:%s — falling back to direct", target_host, target_port)
        remote = await direct_connect(target_host, target_port)
    if remote is None:
        client_w.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n"); await client_w.drain(); return
    remote_r, remote_w = remote
    try:
        if path.startswith(b"http://"):
            path = b"/" + path.split(b"/", 3)[-1:][0] if b"/" in path.split(b"://", 1)[1] else b"/"
        remote_w.write(method + b" " + path + b" HTTP/1.1\r\n")
        for h in headers: remote_w.write(h + b"\r\n")
        remote_w.write(b"\r\n")
        content_length = 0
        for h in headers:
            if h.lower().startswith(b"content-length:"):
                try: content_length = int(h.split(b":")[1].strip())
                except ValueError: pass
                break
        if content_length > 0:
            remote_w.write(await client_r.readexactly(content_length))
        await remote_w.drain()
        status_line = await remote_r.readline()
        if use_tor and any(code in status_line for code in TOR_ERROR_CODES):
            log.warning("Rate limit / auth error from %s — rotating Tor IP...", target_host)
            asyncio.ensure_future(_rotate_and_notify())
        client_w.write(status_line)
        while True:
            h = await remote_r.readline()
            client_w.write(h)
            if h in (b"\r\n", b"\n", b""): break
        await client_w.drain()
        while True:
            d = await remote_r.read(65536)
            if not d: break
            client_w.write(d); await client_w.drain()
    finally:
        try:
            if not remote_w.is_closing(): remote_w.close()
        except Exception:
            pass


async def handle_client(client_r, client_w):
    try:
        try:
            request_line = await asyncio.wait_for(client_r.readline(), timeout=30)
        except asyncio.TimeoutError:
            return
        if not request_line: return
        parts = request_line.strip().split(b" ", 2)
        if len(parts) < 2: return
        method, target = parts[0], parts[1]
        headers = []
        while True:
            try: line = await asyncio.wait_for(client_r.readline(), timeout=10)
            except asyncio.TimeoutError: break
            if line in (b"\r\n", b"\n", b""): break
            headers.append(line.strip())
        if method == b"CONNECT":
            hostport = target.decode("ascii")
            host, _, port_str = hostport.rpartition(":")
            port = int(port_str)
        else:
            target_str = target.decode("ascii")
            if target_str.startswith(("http://", "https://")):
                from urllib.parse import urlparse
                parsed = urlparse(target_str)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
            else:
                host, port = target_str, 80
                for h in headers:
                    if h.lower().startswith(b"host:"):
                        hv = h.split(b":", 1)[1].strip().decode("ascii")
                        host, _, port_str = hv.rpartition(":"); port = int(port_str) if port_str else hv
                        break
        if not host: return
        use_tor = should_route_via_tor(host)
        if method == b"CONNECT":
            await tunnel(client_r, client_w, host, port, use_tor)
        else:
            await handle_http(client_r, client_w, method, target, headers, host, port, use_tor)
    finally:
        try:
            if not client_w.is_closing(): client_w.close()
        except Exception:
            pass


async def main():
    if "--new-ip" in sys.argv:
        ok = await new_tor_ip()
        if ok:
            _clear_zen_pool()
        sys.exit(0 if ok else 1)

    # SIGUSR1 handler for on-demand rotation without killing the session
    def _sigusr1_handler(*_):
        log.info("SIGUSR1 received — rotating Tor IP")
        asyncio.create_task(_rotate_and_notify())
    signal.signal(signal.SIGUSR1, _sigusr1_handler)

    server = await asyncio.start_server(handle_client, *LISTEN, family=socket.AF_INET)
    log.info("Selective proxy on %s:%s (target=%s)", *LISTEN, TARGET)
    async with server: await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
