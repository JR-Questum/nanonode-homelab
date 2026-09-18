#!/usr/bin/env python3
"""Serving the station logo: raw bytes, correct type, byte-identical."""
import json, os, socket, ssl, struct, subprocess, sys, threading, time, zlib

ORIGIN_PORT, TAP_PORT = 18473, 18474
ASSET_PATH = "/assets/150x150/00/00/nanonode.png"

failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)

def tiny_png() -> bytes:
    """A real 1x1 PNG, so the bytes have structure worth preserving."""
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))

PNG = tiny_png()
open("logo.png", "wb").write(PNG)
json.dump({ASSET_PATH: {"file": os.path.abspath("logo.png"), "type": "image/png"}},
          open("assets.json", "w"))

octx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
octx.load_cert_chain("origin-cert.pem", "origin-key.pem")
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", ORIGIN_PORT)); srv.listen(8)
hits = []

def origin():
    while True:
        try:
            raw, _ = srv.accept()
        except OSError:
            return
        def serve(raw=raw):
            try:
                conn = octx.wrap_socket(raw, server_side=True)
                hits.append(conn.recv(8192).split(b" ")[1])
                b = b"REAL-ASSET"
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"
                             b"Content-Length: %d\r\n\r\n%s" % (len(b), b))
                conn.close()
            except Exception:
                pass
        threading.Thread(target=serve, daemon=True).start()
threading.Thread(target=origin, daemon=True).start()
time.sleep(0.3)

env = dict(os.environ, AIRABLE_TAP_UPSTREAM="127.0.0.1",
           AIRABLE_TAP_PORTS=f"{TAP_PORT}:probe:{ORIGIN_PORT}",
           AIRABLE_TAP_LOG=os.path.abspath("as.jsonl"),
           AIRABLE_TAP_CERT=os.path.abspath("cert.pem"),
           AIRABLE_TAP_KEY=os.path.abspath("key.pem"),
           AIRABLE_TAP_ASSETS_FILE=os.path.abspath("assets.json"),
           AIRABLE_TAP_UPSTREAM_VERIFY="0", AIRABLE_TAP_STATUS_PORT="0")
tap = subprocess.Popen([sys.executable, "-u",
                        "../../roles/deploy_airable_proxy/files/airable_tap.py"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", TAP_PORT), timeout=0.2).close(); break
    except OSError:
        time.sleep(0.1)

def fetch(target, host="assets.wifiradiofrontier.com"):
    raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=8)
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    tls = c.wrap_socket(raw, server_hostname=host)
    tls.sendall(b"GET " + target + b" HTTP/1.1\r\nHost: " + host.encode() +
                b"\r\nUser-Agent: FSL IR/0.1\r\n\r\n")
    out = b""
    try:
        while True:
            chunk = tls.recv(8192)
            if not chunk: break
            out += chunk
    except (OSError, ssl.SSLError):
        pass
    try: tls.close()
    except OSError: pass
    return out

got = fetch(ASSET_PATH.encode())
head, _, body = got.partition(b"\r\n\r\n")
check("served as image/png", b"Content-Type: image/png" in head, head[:120])
check("logo bytes are byte-identical", body == PNG,
      f"{len(body)}B vs {len(PNG)}B")
check("content-length matches the image",
      f"Content-Length: {len(PNG)}".encode() in head, head[:160])
check("the real assets host was never contacted", not hits, hits)

got = fetch(b"/assets/150x150/01/93/790723.png")
check("other artwork still comes from upstream", b"REAL-ASSET" in got, got[-60:])

# The updater may not have written anything yet, or Spotify may never have
# played. Forwarding beats serving a broken image.
os.remove("logo.png")
got = fetch(ASSET_PATH.encode())
check("missing artwork falls through to upstream", b"REAL-ASSET" in got, got[-60:])

open("logo.png", "wb").write(PNG)
got = fetch(ASSET_PATH.encode())
check("artwork reappears without a restart", got.endswith(PNG), got[-40:])

# Spotify's CDN serves JPEG whatever the file is called, and the type is
# taken from the extension. Serving JPEG bytes as image/png is a picture
# the device may refuse to draw.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
open("logo.png", "wb").write(JPEG)
got = fetch(ASSET_PATH.encode())
head, _, body = got.partition(b"\r\n\r\n")
check("JPEG in a .png file is served as image/jpeg",
      b"Content-Type: image/jpeg" in head, head[:120])
check("JPEG bytes still delivered intact", body == JPEG, len(body))

time.sleep(0.4)
tap.terminate(); tap.wait(timeout=5); srv.close()
recs = [json.loads(l) for l in open("as.jsonl")]
served = [r for r in recs if r["event"] == "answered" and "asset" in r["reason"]]
check("all three asset serves logged", len(served) == 3, [r.get("reason") for r in recs
                                                     if r["event"] == "answered"])
missing = [r for r in recs if r["event"] == "asset_missing"]
check("the missing-artwork fallthrough is logged", len(missing) == 1,
      [r["event"] for r in recs])

for f in ("as.jsonl", "assets.json", "logo.png"):
    os.remove(f)
print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
