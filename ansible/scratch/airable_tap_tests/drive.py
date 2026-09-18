#!/usr/bin/env python3
"""Drive traffic through the tap and check the bytes come out unchanged."""
import gzip, json, socket, sys, time

PORT = int(sys.argv[1])
HOST = "127.0.0.1"
failures = []

def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail and not cond else ''}")
    if not cond:
        failures.append(name)

def recv_until_len(sock, want):
    buf = b""
    sock.settimeout(5)
    while len(buf) < want:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf

def read_response(sock, method="GET"):
    """Read one HTTP/1.1 response honestly, so we verify framing survived."""
    buf = b""
    sock.settimeout(5)
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return buf, b""
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    hdrs = {}
    for line in head.decode("latin-1").split("\r\n")[1:]:
        k, s, v = line.partition(":")
        if s:
            hdrs[k.strip().lower()] = v.strip()
    if method == "HEAD":
        return head, b""
    if "content-length" in hdrs:
        need = int(hdrs["content-length"])
        while len(rest) < need:
            rest += sock.recv(65536)
        return head, rest[:need]
    if hdrs.get("transfer-encoding", "").lower() == "chunked":
        while not rest.endswith(b"0\r\nX-Trailer: yes\r\n\r\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            rest += chunk
        return head, rest
    if hdrs.get("connection") == "close":
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            rest += chunk
        return head, rest
    return head, rest

# --- keep-alive: three requests down one connection -------------------
s = socket.create_connection((HOST, PORT))
s.sendall(b"GET /plain HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("keepalive #1 status", b"200 OK" in head)
check("keepalive #1 body intact", json.loads(body)["path"] == "/plain", body[:80])

s.sendall(b"POST /plain HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n"
          b"Content-Length: 11\r\n\r\nhello=world")
head, body = read_response(s)
check("keepalive #2 request body forwarded", json.loads(body)["got"] == "hello=world", body[:80])

s.sendall(b"GET /chunked HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("chunked framing preserved verbatim",
      body.startswith(b"5\r\nalpha\r\n4\r\nbeta\r\n") and body.endswith(b"0\r\nX-Trailer: yes\r\n\r\n"),
      body[:60])
s.close()

# --- gzip, HEAD, 204, big body, close-delimited ------------------------
s = socket.create_connection((HOST, PORT))
s.sendall(b"GET /gzip HTTP/1.1\r\nHost: assets.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("gzip body byte-identical", json.loads(gzip.decompress(body))["slogan"] == "hello")

s.sendall(b"HEAD /plain HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s, "HEAD")
check("HEAD returns no body", body == b"", repr(body[:40]))

s.sendall(b"GET /empty HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("204 handled, connection still usable", b"204" in head and body == b"")

s.sendall(b"GET /big HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("40KB body complete after 204", len(body) == 40000, str(len(body)))
s.close()

s = socket.create_connection((HOST, PORT))
s.sendall(b"GET /closed HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("close-delimited body relayed", body == b"no length here", repr(body))
s.close()

# --- garbage: the relay must not care ---------------------------------
s = socket.create_connection((HOST, PORT))
s.sendall(b"\x00\x01\x02 this is not http at all\r\n\r\n")
time.sleep(0.3)
s.close()
check("non-HTTP input did not kill the tap", True)

# tap still alive afterwards?
s = socket.create_connection((HOST, PORT))
s.sendall(b"GET /plain HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
head, body = read_response(s)
check("tap still serving after garbage", b"200 OK" in head)
s.close()

print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
