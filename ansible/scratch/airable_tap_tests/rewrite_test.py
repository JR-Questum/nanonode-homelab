#!/usr/bin/env python3
"""Borrowing a catalogued id: our record must replace the real one.

The device only attaches a description and a logo to a station it holds
a valid Airable id for. Rewriting that id's record is the only way to put
our own text there - so the rewrite must win, and everything else must
still reach the real catalogue.
"""
import json, os, socket, ssl, subprocess, sys, threading, time

ORIGIN_PORT, TAP_PORT = 18463, 18464
PROBE_CN = "airable.wifiradiofrontier.com"
BORROWED = "7478235217276961"

failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)

OURS = {
    "id": ["frontiersmart", "radio", BORROWED],
    "title": "NanonodeRadio",
    "description": "Homelab radio",
    "slogan": "Powered by nanonode",
    "images": [{"url": "http://10.10.40.70:8000/logo.png",
                "size": [150, 150], "type": "cover"}],
    "streams": [{"url": "http://10.10.40.70:8000/nanonode",
                 "codec": {"name": "MP3", "bitrate": 192,
                           "samplerate": 44.1, "channels": 2},
                 "reliability": 1}],
}
json.dump({f"/frontiersmart/radio/{BORROWED}": OURS}, open("rewrites.json", "w"))

octx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
octx.load_cert_chain("origin-cert.pem", "origin-key.pem")
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", ORIGIN_PORT)); srv.listen(8)
upstream_hits = []

def origin():
    while True:
        try:
            raw, _ = srv.accept()
        except OSError:
            return
        def serve(raw=raw):
            try:
                conn = octx.wrap_socket(raw, server_side=True)
                req = conn.recv(8192)
                upstream_hits.append(req.split(b" ")[1])
                b = b'{"title":"REAL AIRABLE","slogan":"Life is Music"}'
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                             b"Content-Length: %d\r\n\r\n%s" % (len(b), b))
                conn.close()
            except Exception:
                pass
        threading.Thread(target=serve, daemon=True).start()
threading.Thread(target=origin, daemon=True).start()
time.sleep(0.3)

if os.path.exists("rw.jsonl"): os.remove("rw.jsonl")
env = dict(os.environ, AIRABLE_TAP_UPSTREAM="127.0.0.1",
           AIRABLE_TAP_PORTS=f"{TAP_PORT}:probe:{ORIGIN_PORT}",
           AIRABLE_TAP_LOG=os.path.abspath("rw.jsonl"),
           AIRABLE_TAP_CERT=os.path.abspath("cert.pem"),
           AIRABLE_TAP_KEY=os.path.abspath("key.pem"),
           AIRABLE_TAP_REWRITES_FILE=os.path.abspath("rewrites.json"),
           AIRABLE_TAP_UPSTREAM_VERIFY="0", AIRABLE_TAP_STATUS_PORT="0")
tap = subprocess.Popen([sys.executable, "-u",
                        "../../roles/deploy_airable_proxy/files/airable_tap.py"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", TAP_PORT), timeout=0.2).close(); break
    except OSError:
        time.sleep(0.1)

def fetch(target):
    raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=8)
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    tls = c.wrap_socket(raw, server_hostname=PROBE_CN)
    tls.sendall(b"GET " + target + b" HTTP/1.1\r\nHost: " + PROBE_CN.encode() +
                b"\r\nConnection: Close\r\n\r\n")
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

got = fetch(f"/frontiersmart/radio/{BORROWED}".encode())
check("borrowed id returns OUR record", b"NanonodeRadio" in got, got[:80])
check("our slogan is delivered", b"Powered by nanonode" in got)
check("our description is delivered", b"Homelab radio" in got)
check("our stream url is delivered", b"10.10.40.70:8000/nanonode" in got)
check("the real record never reaches the device", b"REAL AIRABLE" not in got)
check("the borrowed lookup never hit upstream",
      not any(BORROWED.encode() in h for h in upstream_hits), upstream_hits)

got = fetch(b"/frontiersmart/radio/6882217700593174")
check("a different station still comes from the real catalogue",
      b"REAL AIRABLE" in got, got[-80:])
got = fetch(b"/frontiersmart/radios")
check("menu browsing untouched", b"REAL AIRABLE" in got)

time.sleep(0.5)
tap.terminate(); tap.wait(timeout=5); srv.close()
recs = [json.loads(l) for l in open("rw.jsonl")]
rw = [r for r in recs if r["event"] == "answered"]
check("rewrite logged with its reason", len(rw) == 1 and "rewrite" in rw[0]["reason"],
      [(r["reason"]) for r in rw])

os.remove("rw.jsonl"); os.remove("rewrites.json")
print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
