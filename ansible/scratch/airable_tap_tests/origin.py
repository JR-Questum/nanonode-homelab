#!/usr/bin/env python3
"""Fake Airable origin: keep-alive HTTP/1.1 with the framings that matter."""
import asyncio, gzip, json, sys

PORT = int(sys.argv[1])

def resp(status, headers, body=b""):
    head = f"HTTP/1.1 {status}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    return head.encode() + b"\r\n" + body

async def handle(r, w):
    while True:
        try:
            head = await r.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionResetError):
            break
        lines = head.decode("latin-1").split("\r\n")
        method, path, _ = lines[0].split(" ")
        hdrs = {}
        for line in lines[1:]:
            k, s, v = line.partition(":")
            if s:
                hdrs[k.strip().lower()] = v.strip()
        n = int(hdrs.get("content-length", "0"))
        body = await r.readexactly(n) if n else b""

        if path == "/plain":
            payload = json.dumps({"path": path, "got": body.decode()}).encode()
            w.write(resp("200 OK", {"Content-Type": "application/json",
                                    "Content-Length": len(payload)},
                         b"" if method == "HEAD" else payload))
        elif path == "/chunked":
            parts = [b"alpha", b"beta", b"gamma-" + b"x" * 200]
            out = b""
            for p in parts:
                out += f"{len(p):x}\r\n".encode() + p + b"\r\n"
            out += b"0\r\nX-Trailer: yes\r\n\r\n"
            w.write(resp("200 OK", {"Content-Type": "text/plain",
                                    "Transfer-Encoding": "chunked"}, out))
        elif path == "/gzip":
            payload = gzip.compress(json.dumps({"slogan": "hello", "n": list(range(50))}).encode())
            w.write(resp("200 OK", {"Content-Type": "application/json",
                                    "Content-Encoding": "gzip",
                                    "Content-Length": len(payload)}, payload))
        elif path == "/empty":
            w.write(resp("204 No Content", {}))
        elif path == "/big":
            payload = b"Z" * 40000
            w.write(resp("200 OK", {"Content-Type": "application/octet-stream",
                                    "Content-Length": len(payload)}, payload))
        elif path == "/closed":
            w.write(resp("200 OK", {"Content-Type": "text/plain", "Connection": "close"},
                         b"no length here"))
            await w.drain()
            w.close()
            return
        else:
            w.write(resp("404 Not Found", {"Content-Length": 0}))
        await w.drain()
    w.close()

async def main():
    s = await asyncio.start_server(handle, "127.0.0.1", PORT)
    print(f"origin on {PORT}", flush=True)
    async with s:
        await s.serve_forever()

asyncio.run(main())
