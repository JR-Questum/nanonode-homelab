#!/usr/bin/env python3
"""fetch_artwork.py against a stand-in go-librespot."""
import http.server, json, os, socketserver, struct, subprocess, sys, threading, zlib

SCRIPT = "../../roles/deploy_airable_artwork/files/fetch_artwork.py"
failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond: failures.append(name)

def png(colour):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + colour)) + chunk(b"IEND", b""))

STATE = {"cover": "/img/a.png", "playing": True}
IMAGES = {"/img/a.png": png(b"\xff\x00\x00"), "/img/b.png": png(b"\x00\xff\x00")}
served = []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/status":
            track = ({"album_name": "Tattoo", "album_cover_url":
                      f"http://127.0.0.1:18600{STATE['cover']}"}
                     if STATE["playing"] else None)
            body = json.dumps({"track": track}).encode()
            ctype = "application/json"
        elif self.path in IMAGES:
            served.append(self.path)
            body, ctype = IMAGES[self.path], "image/png"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

class Reusable(socketserver.TCPServer):
    # Without this the port lingers in TIME_WAIT and the next run of the
    # suite cannot bind it, which looks like a flaky test rather than a
    # missing socket option.
    allow_reuse_address = True

srv = Reusable(("127.0.0.1", 18600), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

env = dict(os.environ, ARTWORK_API="http://127.0.0.1:18600",
           ARTWORK_DEST=os.path.abspath("cover.png"),
           ARTWORK_STATE=os.path.abspath("last.txt"))
def run():
    return subprocess.run([sys.executable, SCRIPT], env=env,
                          capture_output=True, text=True)

r = run()
check("first run writes the cover", os.path.exists("cover.png") and
      open("cover.png", "rb").read() == IMAGES["/img/a.png"], r.stderr)
check("first run reported the album", "Tattoo" in r.stderr, r.stderr)

before = len(served)
r = run()
check("unchanged track is not re-downloaded", len(served) == before, served)

STATE["cover"] = "/img/b.png"
r = run()
check("new track replaces the image",
      open("cover.png", "rb").read() == IMAGES["/img/b.png"], r.stderr)

STATE["playing"] = False
r = run()
check("nothing playing leaves the last cover in place",
      open("cover.png", "rb").read() == IMAGES["/img/b.png"] and r.returncode == 0,
      r.stderr)

srv.shutdown()
srv.server_close()
r = run()
check("api down is not an error", r.returncode == 0, r.returncode)
check("api down leaves the cover intact",
      open("cover.png", "rb").read() == IMAGES["/img/b.png"])
check("no temp file left behind", not os.path.exists("cover.png.new"))

env2 = dict(env); env2.pop("ARTWORK_DEST")
r = subprocess.run([sys.executable, SCRIPT], env=env2, capture_output=True, text=True)
check("missing destination is refused", r.returncode == 2, r.returncode)

print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
