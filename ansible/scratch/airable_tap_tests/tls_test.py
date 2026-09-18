#!/usr/bin/env python3
"""TLS passthrough: handshake must complete end-to-end, SNI must be logged."""
import asyncio, json, socket, ssl, subprocess, sys, threading, time

failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond: failures.append(name)

# --- TLS origin -------------------------------------------------------
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("cert.pem", "key.pem")
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 18443)); srv.listen(5)

def origin():
    while True:
        try:
            raw, _ = srv.accept()
        except OSError:
            return
        try:
            conn = ctx.wrap_socket(raw, server_side=True)
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
            conn.close()
        except Exception:
            pass

threading.Thread(target=origin, daemon=True).start()
time.sleep(0.3)

# --- client through the tap, with SNI --------------------------------
cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
cctx.check_hostname = False
cctx.verify_mode = ssl.CERT_NONE
raw = socket.create_connection(("127.0.0.1", 18444), timeout=5)
tls = cctx.wrap_socket(raw, server_hostname="airable.wifiradiofrontier.com")
check("TLS handshake completed through the tap", True)
check("negotiated a real version", tls.version().startswith("TLS"), tls.version())
tls.sendall(b"GET / HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
data = tls.recv(4096)
check("encrypted payload relayed intact", data.endswith(b"hello"), data[-20:])
tls.close()
time.sleep(0.4)

recs = [json.loads(l) for l in open("tls.jsonl")]
hello = [r for r in recs if r["event"] == "tls_hello"]
check("ClientHello observed", len(hello) == 1, [r["event"] for r in recs])
if hello:
    h = hello[0]
    check("SNI extracted", h.get("sni") == "airable.wifiradiofrontier.com", h.get("sni"))
    check("version reported", h.get("version", "").startswith("tls1."), h.get("version"))
close = [r for r in recs if r["event"] == "tls_close"]
check("byte counts recorded both ways",
      close and close[0]["bytes_to_server"] > 0 and close[0]["bytes_to_client"] > 0, close)
check("nothing was decrypted", all("plaintext" not in json.dumps(r) for r in recs))

srv.close()
print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
