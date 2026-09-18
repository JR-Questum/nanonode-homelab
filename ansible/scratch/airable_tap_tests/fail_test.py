#!/usr/bin/env python3
"""Upstream down: the device must be released fast, never left hanging."""
import socket, sys, time
t0 = time.time()
s = socket.create_connection(("127.0.0.1", 18091), timeout=5)
s.sendall(b"GET /x HTTP/1.1\r\nHost: airable.wifiradiofrontier.com\r\n\r\n")
s.settimeout(5)
try:
    data = s.recv(4096)
except (ConnectionResetError, TimeoutError) as exc:
    data = b""
    print(f"      (socket ended with {type(exc).__name__})")
dt = time.time() - t0
ok = data == b"" and dt < 3
print(f"{'PASS' if ok else 'FAIL'}  upstream down closes client in {dt:.2f}s without hanging")
sys.exit(0 if ok else 1)
