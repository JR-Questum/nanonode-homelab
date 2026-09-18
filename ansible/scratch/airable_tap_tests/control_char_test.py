#!/usr/bin/env python3
"""A control character in a request target must not mangle the log view.

The M-9000S sent a target beginning with a control character, which
rewrote the docker logs line and hid what was actually requested.
"""
import json, os, socket, subprocess, sys, time

failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)

for f in ("cc.jsonl",):
    if os.path.exists(f):
        os.remove(f)

origin = subprocess.Popen([sys.executable, "origin.py", "18082"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
env = dict(os.environ, AIRABLE_TAP_UPSTREAM="127.0.0.1",
           AIRABLE_TAP_PORTS="18083:http:18082",
           AIRABLE_TAP_LOG=os.path.abspath("cc.jsonl"),
           AIRABLE_TAP_STATUS_PORT="0")
tap = subprocess.Popen([sys.executable, "-u",
                        "../../roles/deploy_airable_proxy/files/airable_tap.py"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", 18083), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)

s = socket.create_connection(("127.0.0.1", 18083), timeout=5)
# A carriage return mid-target: legal bytes on the wire, ruinous on a terminal.
s.sendall(b"GET /plain\rHIDDEN HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
time.sleep(0.8)
s.close()
time.sleep(0.4)
tap.terminate()
out = tap.stdout.read()
tap.wait(timeout=5)
origin.terminate()

request_lines = [l for l in out.splitlines() if " > GET" in l]
check("request was logged", bool(request_lines), out)
if request_lines:
    line = request_lines[0]
    raw = [c for c in line if ord(c) < 32 or ord(c) == 127]
    check("no raw control characters reach the terminal", not raw,
          [hex(ord(c)) for c in raw])
    check("the control character is shown escaped", "\\x0d" in line, line)
    check("the hidden part is still visible", "HIDDEN" in line, line)

recs = [json.loads(l) for l in open("cc.jsonl")]
req = [r for r in recs if r["event"] == "request"]
check("JSONL keeps the true unmodified target",
      req and req[0]["target"] == "/plain\rHIDDEN",
      repr(req[0]["target"]) if req else None)

os.remove("cc.jsonl")
print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
