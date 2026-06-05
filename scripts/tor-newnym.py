#!/usr/bin/env python3
"""Rotate Tor exit IP via NEWNYM signal. Runs under sg debian-tor for cookie access."""
import asyncio


async def main():
    try:
        r, w = await asyncio.open_connection("127.0.0.1", 9051)
        with open("/run/tor/control.authcookie", "rb") as f:
            cookie = f.read()
        w.write(b"AUTHENTICATE " + cookie.hex().encode() + b"\r\n")
        await w.drain()
        resp = await r.readline()
        assert b"250" in resp, f"auth failed: {resp.decode().strip()}"

        w.write(b"SIGNAL NEWNYM\r\n")
        await w.drain()
        resp = await r.readline()
        assert b"250" in resp, f"newnym failed: {resp.decode().strip()}"
        w.close()
    except Exception as e:
        raise SystemExit(f"NEWNYM failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
    print("NEWNYM OK")