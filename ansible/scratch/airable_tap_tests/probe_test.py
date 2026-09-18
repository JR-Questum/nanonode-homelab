#!/usr/bin/env python3
"""Certificate probe: does the client accept our cert, and what if not?

Two firmwares are simulated. A permissive one that verifies nothing, and
a strict one that checks the chain. The strict case is the important
test: the probe must give up and fall back to passthrough rather than
leaving the device unable to reach its catalogue.
"""
import json, os, socket, ssl, subprocess, sys, threading, time

ORIGIN_PORT, TAP_PORT = 18453, 18454
PROBE_CN = "airable.wifiradiofrontier.com"
ORIGIN_CN = "real.airable.test"

failures = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)

def ensure_cert(cert, key, cn):
    if not os.path.exists(cert):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-keyout", key, "-out", cert, "-days", "30", "-nodes",
                        "-subj", f"/CN={cn}"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

ensure_cert("cert.pem", "key.pem", PROBE_CN)
ensure_cert("origin-cert.pem", "origin-key.pem", ORIGIN_CN)

octx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
octx.load_cert_chain("origin-cert.pem", "origin-key.pem")
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", ORIGIN_PORT)); srv.listen(8)

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
                body = b'{"slogan":"real airable"}'
                if b"frontiersmart" in req:
                    conn.sendall(b"HTTP/1.1 200 OK\r\n"
                                 b"Content-Type: application/json\r\n"
                                 b"Connection: close\r\n\r\n" + body)
                else:
                    conn.sendall(b"HTTP/1.1 200 OK\r\n"
                                 b"Content-Type: application/json\r\n"
                                 b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
                conn.close()
            except Exception:
                pass
        threading.Thread(target=serve, daemon=True).start()
threading.Thread(target=origin, daemon=True).start()
time.sleep(0.3)

def start_tap(logfile):
    env = dict(os.environ,
               AIRABLE_TAP_UPSTREAM="127.0.0.1",
               AIRABLE_TAP_PORTS=f"{TAP_PORT}:probe:{ORIGIN_PORT}",
               AIRABLE_TAP_LOG=os.path.abspath(logfile),
               AIRABLE_TAP_CERT=os.path.abspath("cert.pem"),
               AIRABLE_TAP_KEY=os.path.abspath("key.pem"),
               AIRABLE_TAP_UPSTREAM_VERIFY="0",
               AIRABLE_TAP_PROBE_MAX_FAILURES="2",
               AIRABLE_TAP_STATUS_PORT="0")
    script = os.environ.get(
        "TAP_SCRIPT", "../../roles/deploy_airable_proxy/files/airable_tap.py"
    )
    proc = subprocess.Popen([sys.executable, "-u", script],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", TAP_PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc

def permissive():
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    return c

def strict():
    return ssl.create_default_context()   # system CAs; our self-signed cert fails

def der_of(pem_path):
    return ssl.PEM_cert_to_DER_cert(open(pem_path).read())

def peer_der(tls):
    return tls.getpeercert(binary_form=True)

def records(path):
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]

# ---------------------------------------------------------------- case A
print("=== A. firmware that does not validate ===")
for f in ("probeA.jsonl",):
    if os.path.exists(f): os.remove(f)
tap = start_tap("probeA.jsonl")
raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=5)
tls = permissive().wrap_socket(raw, server_hostname=PROBE_CN)
check("device is offered OUR certificate", peer_der(tls) == der_of("cert.pem"))
tls.sendall(b"GET /radios/nanonode HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
data = tls.recv(8192)
check("real response relayed back", b"real airable" in data, data[-40:])
tls.close(); time.sleep(0.6)
tap.terminate(); tap.wait(timeout=5)

recs = records("probeA.jsonl")
check("logged probe_accepted", any(r["event"] == "probe_accepted" for r in recs))
ex = [r for r in recs if r["event"] == "exchange"]
check("decrypted the request URL", ex and ex[0]["url"].endswith("/radios/nanonode"),
      ex[0]["url"] if ex else None)
check("decrypted the response body",
      ex and "real airable" in ex[0]["resp_body"], ex[0]["resp_body"] if ex else None)

# ---------------------------------------------------------------- case B
print()
print("=== B. firmware that validates (the likely case) ===")
if os.path.exists("probeB.jsonl"): os.remove("probeB.jsonl")
tap = start_tap("probeB.jsonl")
for attempt in (1, 2):
    try:
        raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=5)
        strict().wrap_socket(raw, server_hostname=PROBE_CN).close()
        check(f"strict client rejected our cert (attempt {attempt})", False, "handshake succeeded!")
    except ssl.SSLError as exc:
        check(f"strict client rejected our cert (attempt {attempt})", True, exc)
    time.sleep(0.5)
time.sleep(1.0)

raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=5)
tls = permissive().wrap_socket(raw, server_hostname=PROBE_CN)
check("after refusal the device now sees the REAL server's cert",
      peer_der(tls) == der_of("origin-cert.pem"))
tls.sendall(b"GET /x HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
data = tls.recv(8192)
check("catalogue still reachable through passthrough", b"real airable" in data, data[-40:])
tls.close(); time.sleep(0.5)
tap.terminate(); tap.wait(timeout=5)

recs = records("probeB.jsonl")
rejected = [r for r in recs if r["event"] == "probe_rejected"]
check("both refusals logged", len(rejected) == 2, len(rejected))
check("refusal reason captured",
      rejected and "ALERT" in rejected[0]["error"].upper(),
      rejected[0]["error"] if rejected else None)
check("listener reverted to passthrough",
      any(r["event"] == "probe_reverted" for r in recs),
      [r["event"] for r in recs])
check("no plaintext captured from a refused device",
      not any(r["event"] == "exchange" for r in recs))

# ---------------------------------------------------------------- case C
print()
print("=== C. device that waits for the server to close (the M-9000S) ===")
if os.path.exists("probeC.jsonl"): os.remove("probeC.jsonl")
tap = start_tap("probeC.jsonl")
raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=8)
tls = permissive().wrap_socket(raw, server_hostname=PROBE_CN)
# Exactly what the radio sends: Connection: Close, then it waits.
tls.sendall(b"GET /frontiersmart/radio/7478235217276961 HTTP/1.1\r\n"
            b"Host: airable.wifiradiofrontier.com\r\n"
            b"Connection: Close\r\nContent-Length: 0\r\n\r\n")
body = tls.recv(8192)
check("response received", b"real airable" in body, body[-40:])

# The device never closes first. If the proxy does not end the connection,
# the radio sits here forever - which is what "stuck" looked like.
tls.settimeout(8)
closed = False
try:
    closed = tls.recv(8192) == b""
except (TimeoutError, socket.timeout):
    closed = False
except (ssl.SSLError, OSError):
    closed = True
check("proxy closes the connection so the device is not left hanging", closed)

# Deliberately still holding the client socket open. The radio does not
# hang up either, and a close-delimited response can only be logged once
# the proxy ends the connection itself.
time.sleep(0.8)
recs = records("probeC.jsonl")
ex = [r for r in recs if r["event"] == "exchange"]
check("close-delimited exchange logged without the client hanging up",
      len(ex) == 1, [r["event"] for r in recs])
check("response body captured", ex and "real airable" in ex[0]["resp_body"],
      ex[0]["resp_body"] if ex else None)

try:
    tls.close()
except OSError:
    pass
tap.terminate(); tap.wait(timeout=5)

# ---------------------------------------------------------------- case D
print()
print("=== D. abandoned handshakes must not demote the listener ===")
if os.path.exists("probeD.jsonl"): os.remove("probeD.jsonl")
tap = start_tap("probeD.jsonl")
for _ in range(4):
    # A genuine ClientHello, then hang up before the handshake completes -
    # what a device doing several things at once does routinely.
    raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=5)
    tls = permissive().wrap_socket(raw, server_hostname=PROBE_CN,
                                   do_handshake_on_connect=False)
    tls.setblocking(False)
    try:
        tls.do_handshake()
    except (ssl.SSLWantReadError, ssl.SSLWantWriteError, OSError):
        pass
    raw.close()
    time.sleep(0.3)
time.sleep(1.0)

raw = socket.create_connection(("127.0.0.1", TAP_PORT), timeout=5)
tls = permissive().wrap_socket(raw, server_hostname=PROBE_CN)
check("still terminating TLS after four abandoned handshakes",
      peer_der(tls) == der_of("cert.pem"))
tls.sendall(b"GET /plain HTTP/1.1\r\nHost: " + PROBE_CN.encode() +
            b"\r\nConnection: Close\r\n\r\n")
check("still decrypting and relaying", b"real airable" in tls.recv(8192))
try: tls.close()
except OSError: pass
time.sleep(0.5)
tap.terminate(); tap.wait(timeout=5)

recs = records("probeD.jsonl")
noise = [r for r in recs if r["event"] in ("probe_aborted", "probe_failed")]
check("all four logged as non-refusals", len(noise) == 4, [r["event"] for r in recs])
check("none of them counted towards the revert budget",
      all(r.get("counted", False) is False for r in noise),
      [(r["event"], r.get("counted")) for r in noise])
check("no refusal was recorded",
      not [r for r in recs if r["event"] == "probe_rejected"],
      [r["event"] for r in recs])
check("listener never demoted",
      not [r for r in recs if r["event"] == "probe_reverted"])

srv.close()
print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
