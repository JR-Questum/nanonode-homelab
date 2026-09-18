#!/usr/bin/env python3
"""Transparent TCP tap for the Airable catalogue API.

Managed by Ansible - deploy_airable_proxy. Do not edit on the host.

The Kenwood M-9000S resolves airable.wifiradiofrontier.com through the
homelab's DNS. With a rewrite pointing that name here, the radio's
catalogue traffic lands on this process, which relays it byte-for-byte to
the real Airable host and writes down what it saw.

Bytes are never re-serialised. The HTTP parser runs on a copy of the
stream purely to build readable log records; if it desyncs it gives up on
that connection and the relay carries on regardless. That is the whole
reason this is safe to leave sitting in front of the device's entire
station and podcast catalogue: there is no header rewriting, no chunked
re-encoding, and no keep-alive bookkeeping that could get it wrong.

Per-port modes:
    http   plain relay, parsed into request/response records
    tls    plain relay, not decrypted. The ClientHello is read for SNI and
           version, then the connection passes through untouched.
    raw    plain relay, byte counts only
    probe  TLS is terminated with our own certificate. The M-9000S accepts
           it, which is what makes the rest possible: requests are read in
           the clear, and a configured few are answered here instead of
           being forwarded.

Why anything is answered locally at all: the device only attaches a
description and a logo to a station it holds a real Airable id for. A
locally added stream has none - the firmware sends seven bytes of
uninitialised memory as the lookup path - so the only route to those
fields is to borrow a catalogued station's id and answer for it.

Reads configuration from the environment:
    AIRABLE_TAP_UPSTREAM        IP of the real Airable host. An IP, never a
                                name - DNS here now points back at us.
    AIRABLE_TAP_PORTS           comma-separated port:mode[:upstream_port]
                                (default 80:http,443:tls)
    AIRABLE_TAP_LOG             JSONL path; empty logs to stdout only
    AIRABLE_TAP_LOG_MAX_BYTES   rotate to .1 past this size (0 disables)
    AIRABLE_TAP_MAX_BODY        bytes of each body kept per message
    AIRABLE_TAP_CONNECT_TIMEOUT seconds to reach upstream
    AIRABLE_TAP_IDLE_TIMEOUT    seconds of silence before closing (0 disables)
    AIRABLE_TAP_STATUS_PORT     health/stats endpoint (0 disables)

Certificate probe (mode "probe" on a port, e.g. AIRABLE_TAP_PORTS=443:probe):
    AIRABLE_TAP_CERT            PEM certificate to present to the device
    AIRABLE_TAP_KEY             its private key
    AIRABLE_TAP_CIPHERS         OpenSSL cipher string for the device side
    AIRABLE_TAP_PROBE_MAX_FAILURES
                                rejected handshakes tolerated before the
                                listener drops back to passthrough
    AIRABLE_TAP_UPSTREAM_HOST   name to verify the real server against
    AIRABLE_TAP_UPSTREAM_VERIFY 0 to skip verifying the real server
    AIRABLE_TAP_REWRITES_FILE   JSON object of {target substring: record},
                                served instead of the real catalogue entry
    AIRABLE_TAP_ASSETS_FILE     JSON object of {target substring:
                                {file, type}}, served as raw bytes - the
                                station logo lives here. Files are read per
                                request, so whatever writes them can keep
                                them current without a restart.
"""

from __future__ import annotations

import asyncio
import functools
import gzip
import json
import os
import signal
import socket
import ssl
import sys
import time
import zlib
from collections import deque
from datetime import datetime, timezone

READ_SIZE = 65536

# A header block larger than this is not something we can usefully parse.
# The relay keeps running; only the logging gives up.
HEADER_LIMIT = 64 * 1024

STATUS_NO_BODY = {204, 304}


def env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None else value


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


_CONTROL = {i: f"\\x{i:02x}" for i in range(32)}
_CONTROL[127] = "\\x7f"


def printable(text: str, limit: int = 300) -> str:
    """Escape control characters before they reach a terminal.

    Everything the device sends is untrusted as far as the log is
    concerned. A bare CR in a request target rewrites the line in
    docker logs and hides the very thing being investigated.
    """
    out = text.translate(_CONTROL)
    return out if len(out) <= limit else out[:limit] + "..."


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_type(blob: bytes, fallback: str) -> str:
    """Content type from the bytes, not from the filename.

    Artwork is whatever the source hands over - Spotify's CDN serves JPEG
    regardless of what the file ends up being called - and a JPEG labelled
    image/png is a picture the device may simply refuse to draw.
    """
    for prefix, kind in _MAGIC:
        if blob.startswith(prefix):
            return kind
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def fmt_addr(addr) -> str:
    if not addr:
        return "?"
    return f"{addr[0]}:{addr[1]}"


class Config:
    def __init__(self) -> None:
        self.upstream = env_str("AIRABLE_TAP_UPSTREAM", "").strip()
        self.listeners = self._parse_ports(
            env_str("AIRABLE_TAP_PORTS", "80:http,443:tls")
        )
        self.log_path = env_str("AIRABLE_TAP_LOG", "").strip()
        self.log_max_bytes = env_int("AIRABLE_TAP_LOG_MAX_BYTES", 64 * 1024 * 1024)
        self.max_body = env_int("AIRABLE_TAP_MAX_BODY", 65536)
        self.connect_timeout = env_int("AIRABLE_TAP_CONNECT_TIMEOUT", 10)
        self.idle_timeout = env_int("AIRABLE_TAP_IDLE_TIMEOUT", 600)
        self.status_port = env_int("AIRABLE_TAP_STATUS_PORT", 8081)

        self.cert = env_str("AIRABLE_TAP_CERT", "").strip()
        self.key = env_str("AIRABLE_TAP_KEY", "").strip()
        # The device offers TLS 1.2 with an old suite list. OpenSSL 3
        # rejects some of those at the default security level, and a
        # handshake we lose on ciphers would be misread as the firmware
        # refusing our certificate - the one thing the probe must not
        # get wrong.
        self.ciphers = env_str("AIRABLE_TAP_CIPHERS", "DEFAULT:@SECLEVEL=1")
        self.probe_max_failures = env_int("AIRABLE_TAP_PROBE_MAX_FAILURES", 2)
        self.handshake_timeout = env_int("AIRABLE_TAP_HANDSHAKE_TIMEOUT", 10)
        self.upstream_host = env_str(
            "AIRABLE_TAP_UPSTREAM_HOST", "airable.wifiradiofrontier.com"
        ).strip()
        self.upstream_verify = env_int("AIRABLE_TAP_UPSTREAM_VERIFY", 1) != 0

        # Substring -> replacement record. A catalogue entry the device
        # already holds a valid Airable id for is the only place it will
        # attach a description and a logo, so borrowing one is the only
        # route to those fields for a station Airable never issued.
        self.rewrites: list[tuple[str, str]] = []
        path = env_str("AIRABLE_TAP_REWRITES_FILE", "").strip()
        if path:
            with open(path, encoding="utf-8") as fh:
                try:
                    table = json.load(fh)
                except ValueError as exc:
                    sys.exit(f"{path} is not valid JSON: {exc}")
            if not isinstance(table, dict):
                sys.exit(f"{path} must be a JSON object of match -> record")
            for match, record in table.items():
                self.rewrites.append(
                    (match, json.dumps(record, ensure_ascii=False))
                )

        # Substring -> (path on disk, content type). The station logo is
        # fetched from the assets host as an ordinary image, so serving one
        # is the same trick as a catalogue rewrite with a different body.
        # Paths, not bytes: something else keeps the artwork current, and
        # reading per request means it never needs a restart to be picked
        # up.
        self.assets: list[tuple[str, str, str]] = []
        path = env_str("AIRABLE_TAP_ASSETS_FILE", "").strip()
        if path:
            with open(path, encoding="utf-8") as fh:
                try:
                    table = json.load(fh)
                except ValueError as exc:
                    sys.exit(f"{path} is not valid JSON: {exc}")
            for match, spec in table.items():
                self.assets.append(
                    (match, spec["file"],
                     spec.get("type", "application/octet-stream"))
                )

        if not self.upstream:
            sys.exit("AIRABLE_TAP_UPSTREAM is required")
        try:
            socket.inet_aton(self.upstream)
        except OSError:
            # A hostname would resolve through the very DNS rewrite that
            # sends traffic here, and the tap would talk to itself.
            sys.exit(
                f"AIRABLE_TAP_UPSTREAM must be an IPv4 address, got {self.upstream!r}"
            )
        if not self.listeners:
            sys.exit("AIRABLE_TAP_PORTS is empty")
        if any(mode == "probe" for _, mode, _ in self.listeners):
            if not (self.cert and self.key):
                sys.exit(
                    "probe mode needs AIRABLE_TAP_CERT and AIRABLE_TAP_KEY"
                )

    @staticmethod
    def _parse_ports(raw: str) -> list[tuple[int, str, int]]:
        """Parse "port:mode[:upstream_port]" specs.

        The upstream port defaults to the listening port, which is what
        the DNS-rewrite deployment always wants. The override exists so
        the tap can be exercised against a local origin on a spare port.
        """
        out = []
        for spec in raw.split(","):
            spec = spec.strip()
            if not spec:
                continue
            fields = spec.split(":")
            if len(fields) > 3:
                sys.exit(f"malformed port spec {spec!r}")
            port = int(fields[0])
            raw_mode = fields[1] if len(fields) > 1 and fields[1] else "http"
            mode = raw_mode.strip().lower()
            if mode not in ("http", "tls", "raw", "probe"):
                sys.exit(f"unknown tap mode {mode!r} in {spec!r}")
            upstream_port = int(fields[2]) if len(fields) > 2 else port
            out.append((port, mode, upstream_port))
        return out


class Log:
    """Full detail as JSONL on disk, one readable line per event on stdout.

    The stdout view is the point during a capture session: run
    `docker logs -f` next to the radio and watch what each button press
    produces. The file is what gets read afterwards.
    """

    def __init__(self, path: str, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.fh = open(path, "a", encoding="utf-8") if path else None

    def record(self, rec: dict, line: str | None = None) -> None:
        if self.fh is not None:
            line_out = json.dumps({"ts": now_iso(), **rec}, ensure_ascii=False)
            self.fh.write(line_out + "\n")
            self.fh.flush()
            self._rotate()
        if line:
            print(line, flush=True)

    def _rotate(self) -> None:
        if not self.max_bytes or self.fh.tell() < self.max_bytes:
            return
        self.fh.close()
        os.replace(self.path, self.path + ".1")
        self.fh = open(self.path, "a", encoding="utf-8")


class HttpParser:
    """Incremental HTTP/1.1 parser fed a copy of one direction of a relay.

    Deliberately forgiving: anything it cannot follow sets `desynced` and
    it stops looking at the connection. Nothing here can stall or alter
    the bytes in flight.
    """

    def __init__(
        self, is_response: bool, max_body: int, on_message, head_hook=None
    ) -> None:
        self.is_response = is_response
        self.max_body = max_body
        self.on_message = on_message
        self.head_hook = head_hook
        self.buf = bytearray()
        self.state = "head"
        self.desynced = False
        self._reset()

    def _reset(self) -> None:
        self.start_line = ""
        self.headers: list[tuple[str, str]] = []
        self.body = bytearray()
        self.body_len = 0
        self.truncated = False
        self.remaining = 0
        self.started = 0.0

    def feed(self, data: bytes) -> None:
        if self.desynced:
            return
        self.buf += data
        while self._step():
            pass

    def eof(self) -> None:
        if self.desynced:
            return
        if self.state == "body-eof":
            self._emit(complete=True)
        elif self.state != "head" or self.start_line:
            self.truncated = True
            self._emit(complete=False)
        self.state = "head"

    def header(self, name: str, default: str = "") -> str:
        name = name.lower()
        for key, value in self.headers:
            if key == name:
                return value
        return default

    def _step(self) -> bool:
        handler = getattr(self, "_step_" + self.state.replace("-", "_"), None)
        return bool(handler and handler())

    def _step_head(self) -> bool:
        # Tolerate the stray CRLFs some clients send between messages.
        while self.buf[:2] == b"\r\n":
            del self.buf[:2]
        end = self.buf.find(b"\r\n\r\n")
        if end < 0:
            if len(self.buf) > HEADER_LIMIT:
                self._desync("header block too large")
            return False
        block = bytes(self.buf[:end])
        del self.buf[: end + 4]

        lines = block.split(b"\r\n")
        self.start_line = lines[0].decode("latin-1")
        if not self._plausible_start_line():
            self._desync(f"unparseable start line {self.start_line[:80]!r}")
            return False

        self.headers = []
        for raw in lines[1:]:
            key, sep, value = raw.decode("latin-1").partition(":")
            if sep:
                self.headers.append((key.strip().lower(), value.strip()))

        self.started = time.monotonic()
        return self._begin_body()

    def _plausible_start_line(self) -> bool:
        parts = self.start_line.split(" ")
        if self.is_response:
            return (
                len(parts) >= 2
                and parts[0].startswith("HTTP/")
                and parts[1].isdigit()
            )
        return len(parts) == 3 and parts[2].startswith("HTTP/")

    def _begin_body(self) -> bool:
        if self.head_hook is not None and self.head_hook(self):
            self._emit(complete=True)
            return True

        encoding = self.header("transfer-encoding").lower()
        length = self.header("content-length")
        if "chunked" in encoding:
            self.state = "chunk-size"
        elif length.isdigit():
            self.remaining = int(length)
            if self.remaining == 0:
                self._emit(complete=True)
                return True
            self.state = "body"
        elif self.is_response:
            # No framing at all: the body runs until the server closes.
            self.state = "body-eof"
        else:
            self._emit(complete=True)
        return True

    def _step_body(self) -> bool:
        take = min(self.remaining, len(self.buf))
        if take:
            self._capture(self.buf[:take])
            del self.buf[:take]
            self.remaining -= take
        if self.remaining == 0:
            self._emit(complete=True)
            return True
        return False

    def _step_body_eof(self) -> bool:
        if self.buf:
            self._capture(self.buf)
            self.buf.clear()
        return False

    def _step_chunk_size(self) -> bool:
        end = self.buf.find(b"\r\n")
        if end < 0:
            if len(self.buf) > 1024:
                self._desync("chunk size line too long")
            return False
        line = bytes(self.buf[:end]).split(b";")[0].strip()
        del self.buf[: end + 2]
        try:
            self.remaining = int(line, 16)
        except ValueError:
            self._desync(f"bad chunk size {line[:32]!r}")
            return False
        self.state = "trailer" if self.remaining == 0 else "chunk-data"
        return True

    def _step_chunk_data(self) -> bool:
        take = min(self.remaining, len(self.buf))
        if take:
            self._capture(self.buf[:take])
            del self.buf[:take]
            self.remaining -= take
        if self.remaining == 0:
            self.state = "chunk-crlf"
            return True
        return False

    def _step_chunk_crlf(self) -> bool:
        if len(self.buf) < 2:
            return False
        del self.buf[:2]
        self.state = "chunk-size"
        return True

    def _step_trailer(self) -> bool:
        end = self.buf.find(b"\r\n")
        if end < 0:
            return False
        line = bytes(self.buf[:end])
        del self.buf[: end + 2]
        if not line:
            self._emit(complete=True)
            return True
        return True  # a trailer header; skip it and look for the next line

    def _capture(self, chunk) -> None:
        self.body_len += len(chunk)
        room = self.max_body - len(self.body)
        if room > 0:
            self.body += chunk[:room]
        if len(chunk) > max(room, 0):
            self.truncated = True

    def _desync(self, reason: str) -> None:
        self.desynced = True
        self.buf.clear()
        self.on_message(None, reason)

    def _emit(self, complete: bool) -> None:
        message = {
            "start_line": self.start_line,
            "headers": dict(self.headers),
            "body": self._render_body(),
            "body_bytes": self.body_len,
            "truncated": self.truncated,
            "complete": complete,
            "elapsed_ms": (
                int((time.monotonic() - self.started) * 1000) if self.started else 0
            ),
        }
        self.state = "head"
        self._reset()
        self.on_message(message, None)

    def _render_body(self) -> str:
        raw = bytes(self.body)
        if not raw:
            return ""
        encoding = self.header("content-encoding").lower()
        if not self.truncated:
            # Only worth attempting on a whole body; a truncated gzip
            # stream just raises and we keep the compressed bytes.
            try:
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    raw = zlib.decompress(raw)
            except Exception:
                pass
        text = raw.decode("utf-8", "replace")
        limit = self.max_body * 8
        return text if len(text) <= limit else text[:limit] + "...[cut]"


class HttpObserver:
    """Pairs requests with responses and turns them into log records."""

    def __init__(self, cid: str, peer: str, port: int, cfg: Config, log: Log) -> None:
        self.cid = cid
        self.peer = peer
        self.port = port
        self.log = log
        self.pending: deque[dict] = deque()
        self.exchanges = 0
        self.to_server = 0
        self.to_client = 0
        self.requests = HttpParser(False, cfg.max_body, self._on_request)
        self.responses = HttpParser(
            True, cfg.max_body, self._on_response, self._response_has_no_body
        )

    def client(self, data: bytes) -> None:
        self.to_server += len(data)
        self.requests.feed(data)

    def server(self, data: bytes) -> None:
        self.to_client += len(data)
        self.responses.feed(data)

    def eof(self) -> None:
        self.requests.eof()
        self.responses.eof()
        for orphan in self.pending:
            self.log.record(
                {"event": "orphan_request", "conn": self.cid,
                 "peer": self.peer, **orphan},
                line=(f"{clock()} {self.cid} !! no response to "
                      f"{printable(orphan['method'])} "
                      f"{printable(orphan['url'])}"),
            )
        self.pending.clear()
        self.log.record(
            {"event": "http_close", "conn": self.cid, "peer": self.peer,
             "port": self.port, "exchanges": self.exchanges,
             "bytes_to_server": self.to_server,
             "bytes_to_client": self.to_client},
        )

    def _response_has_no_body(self, parser: HttpParser) -> bool:
        status = self._status(parser.start_line)
        if status in STATUS_NO_BODY or 100 <= status < 200:
            return True
        return bool(self.pending) and self.pending[0]["method"] == "HEAD"

    @staticmethod
    def _status(start_line: str) -> int:
        parts = start_line.split(" ")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    def _on_request(self, message, desync) -> None:
        if desync:
            self._log_desync("request", desync)
            return
        method, _, rest = message["start_line"].partition(" ")
        target = rest.rpartition(" ")[0] or rest
        host = message["headers"].get("host", "")
        entry = {
            "method": method,
            "host": host,
            "target": target,
            "url": f"{host}{target}",
            "req_headers": message["headers"],
            "req_body": message["body"],
            "t0": time.monotonic(),
        }
        self.pending.append(entry)
        self.log.record(
            {"event": "request", "conn": self.cid, "peer": self.peer,
             **{k: v for k, v in entry.items() if k != "t0"}},
            line=f"{clock()} {self.cid} > {method} {printable(entry['url'])}",
        )

    def _on_response(self, message, desync) -> None:
        if desync:
            self._log_desync("response", desync)
            return
        status = self._status(message["start_line"])
        if 100 <= status < 200:
            return  # interim response; the real one still owes us a body

        request = self.pending.popleft() if self.pending else {}
        self.exchanges += 1
        headers = message["headers"]
        elapsed = (
            int((time.monotonic() - request["t0"]) * 1000)
            if request
            else message["elapsed_ms"]
        )
        record = {
            "event": "exchange",
            "conn": self.cid,
            "peer": self.peer,
            "port": self.port,
            "method": request.get("method", "?"),
            "host": request.get("host", ""),
            "target": request.get("target", ""),
            "url": request.get("url", "?"),
            "req_headers": request.get("req_headers", {}),
            "req_body": request.get("req_body", ""),
            "status": status,
            "resp_headers": headers,
            "resp_body": message["body"],
            "resp_bytes": message["body_bytes"],
            "resp_truncated": message["truncated"],
            "complete": message["complete"],
            "ms": elapsed,
        }
        ctype = headers.get("content-type", "-").split(";")[0]
        self.log.record(
            record,
            line=(
                f"{clock()} {self.cid} < {status} {printable(ctype)} "
                f"{message['body_bytes']}B {elapsed}ms  "
                f"{printable(record['url'])}"
            ),
        )

    def _log_desync(self, direction: str, reason: str) -> None:
        self.log.record(
            {"event": "parse_desync", "conn": self.cid, "peer": self.peer,
             "direction": direction, "reason": reason},
            line=(f"{clock()} {self.cid} ?? {direction} parse gave up: "
                  f"{reason} (relay unaffected)"),
        )


class TlsObserver:
    """Reads the ClientHello for SNI, then just counts bytes.

    Nothing is decrypted. The question this answers is whether the device
    uses 443 at all, and for which names.
    """

    def __init__(self, cid: str, peer: str, port: int, cfg: Config, log: Log) -> None:
        self.cid = cid
        self.peer = peer
        self.port = port
        self.log = log
        self.buf = bytearray()
        self.hello: dict | None = None
        self.to_server = 0
        self.to_client = 0

    def client(self, data: bytes) -> None:
        self.to_server += len(data)
        if self.hello is not None:
            return
        self.buf += data
        try:
            parsed = parse_client_hello(bytes(self.buf))
        except Exception as exc:  # noqa: BLE001 - a hello we cannot read is not fatal
            parsed = {"error": f"{type(exc).__name__}: {exc}"}
        if parsed is None:
            return
        self.hello = parsed
        self.buf.clear()
        sni = parsed.get("sni", "-")
        version = parsed.get("version", "?")
        alpn = ",".join(parsed.get("alpn", [])) or "-"
        self.log.record(
            {"event": "tls_hello", "conn": self.cid, "peer": self.peer,
             "port": self.port, **parsed},
            line=(f"{clock()} {self.cid} ~ TLS {printable(sni)} "
                  f"({printable(version)}, alpn={printable(alpn)}) "
                  f"passthrough"),
        )

    def server(self, data: bytes) -> None:
        self.to_client += len(data)

    def eof(self) -> None:
        self.log.record(
            {"event": "tls_close", "conn": self.cid, "peer": self.peer,
             "port": self.port, "sni": (self.hello or {}).get("sni", ""),
             "bytes_to_server": self.to_server,
             "bytes_to_client": self.to_client},
        )


class RawObserver:
    """Counts bytes for a port we have nothing clever to say about."""

    def __init__(self, cid: str, peer: str, port: int, cfg: Config, log: Log) -> None:
        self.cid, self.peer, self.port, self.log = cid, peer, port, log
        self.to_server = self.to_client = 0

    def client(self, data: bytes) -> None:
        self.to_server += len(data)

    def server(self, data: bytes) -> None:
        self.to_client += len(data)

    def eof(self) -> None:
        self.log.record(
            {"event": "raw_close", "conn": self.cid, "peer": self.peer,
             "port": self.port, "bytes_to_server": self.to_server,
             "bytes_to_client": self.to_client},
        )


TLS_VERSIONS = {0x0301: "tls1.0", 0x0302: "tls1.1", 0x0303: "tls1.2", 0x0304: "tls1.3"}


def parse_client_hello(data: bytes) -> dict | None:
    """Return hello details, or None while more bytes are still needed."""
    if len(data) < 5:
        return None
    if data[0] != 0x16:
        return {"error": "not a TLS handshake", "first_byte": data[0]}
    record_len = int.from_bytes(data[3:5], "big")
    if len(data) < 5 + record_len:
        # A ClientHello split across records is legal but vanishingly rare;
        # give it one record's worth and report what we have.
        if len(data) < 5 + min(record_len, 16384):
            return None
    body = data[5 : 5 + record_len]
    try:
        return _parse_hello_body(body)
    except (IndexError, ValueError) as exc:
        return {"error": f"malformed ClientHello: {exc}"}


def _parse_hello_body(body: bytes) -> dict:
    if not body or body[0] != 0x01:
        return {"error": "not a ClientHello"}
    pos = 4  # handshake type + 3-byte length
    legacy = int.from_bytes(body[pos : pos + 2], "big")
    pos += 2 + 32  # version + random
    pos += 1 + body[pos]  # session id
    pos += 2 + int.from_bytes(body[pos : pos + 2], "big")  # cipher suites
    pos += 1 + body[pos]  # compression methods

    out: dict = {"version": TLS_VERSIONS.get(legacy, hex(legacy))}
    if pos + 2 > len(body):
        return out
    end = pos + 2 + int.from_bytes(body[pos : pos + 2], "big")
    pos += 2
    while pos + 4 <= min(end, len(body)):
        ext_type = int.from_bytes(body[pos : pos + 2], "big")
        ext_len = int.from_bytes(body[pos + 2 : pos + 4], "big")
        ext = body[pos + 4 : pos + 4 + ext_len]
        pos += 4 + ext_len
        # One unreadable extension should cost us that extension, not the
        # SNI sitting next to it.
        try:
            if ext_type == 0x0000 and len(ext) >= 5:
                # SNI host names are sent as A-labels, so they are ASCII on
                # the wire; decoding as IDNA here would reject them.
                name = ext[5 : 5 + int.from_bytes(ext[3:5], "big")]
                out["sni"] = name.decode("ascii", "replace")
            elif ext_type == 0x0010:
                names, cursor = [], 2
                while cursor < len(ext):
                    size = ext[cursor]
                    label = ext[cursor + 1 : cursor + 1 + size]
                    names.append(label.decode("ascii", "replace"))
                    cursor += 1 + size
                out["alpn"] = names
            elif ext_type == 0x002B:
                offered = [
                    int.from_bytes(ext[i : i + 2], "big")
                    for i in range(1, len(ext) - 1, 2)
                ]
                out["supported_versions"] = [
                    TLS_VERSIONS.get(v, hex(v)) for v in offered
                ]
        except (IndexError, ValueError, UnicodeError) as exc:
            out.setdefault("extension_errors", []).append(f"{hex(ext_type)}: {exc}")
    if "tls1.3" in out.get("supported_versions", []):
        out["version"] = "tls1.3"
    return out


OBSERVERS = {"http": HttpObserver, "tls": TlsObserver, "raw": RawObserver}

# A probe listener that gets refused falls back to this.
PROBE_FALLBACK = "tls"


def request_target(head: bytes) -> bytes | None:
    """The target from a request head, without decoding it."""
    line = head.split(b"\r\n", 1)[0]
    parts = line.split(b" ")
    return parts[1] if len(parts) == 3 else None


def build_server_context(cfg: Config) -> ssl.SSLContext:
    """The certificate we offer the radio."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cfg.cert, cfg.key)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if cfg.ciphers:
        ctx.set_ciphers(cfg.ciphers)
    return ctx


def build_client_context(cfg: Config) -> ssl.SSLContext:
    """Our own connection onward to the real Airable host."""
    ctx = ssl.create_default_context()
    if not cfg.upstream_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def is_refusal(exc: BaseException) -> bool:
    """Did the peer actually reject our certificate?

    Only a TLS alert from the client counts. A reset, an EOF or a timeout
    means the connection went away, which says nothing about trust - and
    treating it as a refusal would demote the listener for network noise
    and silently stop rewriting anything.
    """
    reason = str(getattr(exc, "reason", "") or "")
    return "ALERT" in reason.upper()


def ssl_reason(exc: BaseException | None) -> str:
    """The bit of an SSLError worth putting in a log line.

    A client that dislikes our certificate says so in the alert, and the
    alert name is the whole answer: TLSV1_ALERT_UNKNOWN_CA is a device
    checking a CA bundle, TLSV1_ALERT_CERTIFICATE_UNKNOWN is usually
    pinning or a name mismatch.
    """
    if exc is None:
        return "no exception reported"
    reason = getattr(exc, "reason", None)
    return f"{type(exc).__name__}: {reason or exc}"

STATS = {
    "started": now_iso(),
    "connections": 0,
    "active": 0,
    "upstream_errors": 0,
    "exchanges": 0,
    "last_error": None,
    "handshakes_accepted": 0,
    "handshakes_rejected": 0,
    "probe_state": "not running",
    "answered_locally": 0,
}


class Tap:
    def __init__(self, cfg: Config, log: Log) -> None:
        self.cfg = cfg
        self.log = log
        self.seq = 0
        self.client_ctx: ssl.SSLContext | None = None
        self.server_ctx: ssl.SSLContext | None = None

    async def handle(
        self, client_r, client_w, port: int, mode: str, upstream_port: int
    ) -> None:
        self.seq += 1
        cid = f"c{self.seq}"
        peer = fmt_addr(client_w.get_extra_info("peername"))
        STATS["connections"] += 1
        STATS["active"] += 1
        set_nodelay(client_w)

        upstream_w = None
        try:
            try:
                upstream_r, upstream_w = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.upstream, upstream_port),
                    timeout=self.cfg.connect_timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                # Fail fast and loudly rather than holding the device open:
                # a reset makes the radio retry, a hang makes it wedge.
                STATS["upstream_errors"] += 1
                STATS["last_error"] = f"{type(exc).__name__}: {exc}"
                self.log.record(
                    {"event": "upstream_unreachable", "conn": cid, "peer": peer,
                     "port": port, "error": str(exc),
                     "upstream": f"{self.cfg.upstream}:{upstream_port}"},
                    line=(f"{clock()} {cid} XX upstream "
                          f"{self.cfg.upstream}:{upstream_port} "
                          f"unreachable: {exc}"),
                )
                return
            set_nodelay(upstream_w)

            observer = OBSERVERS[mode](cid, peer, port, self.cfg, self.log)
            self.log.record(
                {"event": "open", "conn": cid, "peer": peer,
                 "port": port, "mode": mode}
            )
            await asyncio.gather(
                self._pump(client_r, upstream_w, observer.client),
                self._pump(upstream_r, client_w, observer.server),
            )
            observer.eof()
            STATS["exchanges"] += getattr(observer, "exchanges", 0)
        finally:
            STATS["active"] -= 1
            for writer in (client_w, upstream_w):
                close(writer)

    async def handle_probe(
        self, client_r, client_w, port: int, upstream_port: int, listener
    ) -> None:
        """Offer the device our certificate and see what it does."""
        self.seq += 1
        cid = f"p{self.seq}"
        peer = fmt_addr(client_w.get_extra_info("peername"))
        STATS["connections"] += 1
        STATS["active"] += 1
        set_nodelay(client_w)

        upstream_w = None
        try:
            buffered = bytearray()
            hello = None
            while hello is None:
                chunk = await client_r.read(READ_SIZE)
                if not chunk:
                    return
                buffered += chunk
                try:
                    hello = parse_client_hello(bytes(buffered))
                except Exception as exc:  # noqa: BLE001
                    hello = {"error": f"{type(exc).__name__}: {exc}"}
            self.log.record(
                {"event": "tls_hello", "conn": cid, "peer": peer,
                 "port": port, **hello}
            )

            stream = SslStream(
                self.server_ctx, client_r, client_w, self.cfg.idle_timeout
            )
            stream.feed(bytes(buffered))
            try:
                await stream.handshake()
            except HandshakeAborted as exc:
                # Ordinary noise. Never counted: demoting on this would
                # silently disable interception for the rest of the run.
                self.log.record(
                    {"event": "probe_aborted", "conn": cid, "peer": peer,
                     "port": port, "error": str(exc)},
                    line=f"{clock()} {cid} .. handshake abandoned by the device",
                )
                return
            except (ssl.SSLError, OSError) as exc:
                refusal = is_refusal(exc)
                if refusal:
                    STATS["handshakes_rejected"] += 1
                STATS["last_error"] = ssl_reason(exc)
                self.log.record(
                    {"event": "probe_rejected" if refusal else "probe_failed",
                     "conn": cid, "peer": peer, "port": port,
                     "error": ssl_reason(exc), "counted": refusal,
                     "rejected_so_far": STATS["handshakes_rejected"]},
                    line=(f"{clock()} {cid} !! certificate REFUSED by the "
                          f"device: {ssl_reason(exc)}" if refusal else
                          f"{clock()} {cid} .. handshake failed, not a "
                          f"refusal: {ssl_reason(exc)}"),
                )
                if (refusal
                        and STATS["handshakes_rejected"]
                        >= self.cfg.probe_max_failures):
                    asyncio.get_running_loop().create_task(
                        listener.demote("certificate refused")
                    )
                return

            STATS["handshakes_accepted"] += 1
            self.log.record(
                {"event": "probe_accepted", "conn": cid, "peer": peer,
                 "port": port, "sni": hello.get("sni", "")},
                line=(f"{clock()} {cid} ** certificate ACCEPTED by the device "
                      f"- decrypting"),
            )

            observer = HttpObserver(cid, peer, port, self.cfg, self.log)

            # Read the request head before deciding what to do with it.
            head = bytearray()
            while b"\r\n\r\n" not in head and len(head) <= HEADER_LIMIT:
                chunk = await stream.read()
                if not chunk:
                    break
                head += chunk
            if not head:
                return

            target = request_target(bytes(head))
            if target is not None:
                readable = target.decode("latin-1")
                for match, asset_path, ctype in self.cfg.assets:
                    if match not in readable:
                        continue
                    try:
                        with open(asset_path, "rb") as fh:
                            blob = fh.read()
                    except OSError as exc:
                        # Nothing has written the artwork yet. Forwarding
                        # gives the device a clean 404 from the real host
                        # rather than a broken image from us.
                        self.log.record(
                            {"event": "asset_missing", "conn": cid,
                             "peer": peer, "path": asset_path,
                             "error": str(exc)},
                            line=(f"{clock()} {cid} .. no artwork at "
                                  f"{asset_path}, forwarding upstream"),
                        )
                        break
                    await self._answer_locally(
                        stream, observer, cid, peer, port, bytes(head),
                        target, blob, f"asset {match}",
                        sniff_type(blob, ctype)
                    )
                    return
                for match, record in self.cfg.rewrites:
                    if match in readable:
                        await self._answer_locally(
                            stream, observer, cid, peer, port, bytes(head),
                            target, record, f"rewrite {match}"
                        )
                        return

            try:
                upstream_r, upstream_w = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.cfg.upstream,
                        upstream_port,
                        ssl=self.client_ctx,
                        server_hostname=hello.get("sni") or self.cfg.upstream_host,
                    ),
                    timeout=self.cfg.connect_timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                STATS["upstream_errors"] += 1
                STATS["last_error"] = f"upstream tls: {ssl_reason(exc)}"
                self.log.record(
                    {"event": "upstream_tls_failed", "conn": cid, "peer": peer,
                     "port": port, "error": str(exc)},
                    line=(f"{clock()} {cid} XX real server unreachable over "
                          f"TLS: {ssl_reason(exc)}"),
                )
                return

            self._observe(observer.client, bytes(head))
            upstream_w.write(bytes(head))
            await upstream_w.drain()
            await asyncio.gather(
                self._pump_from_tls(stream, upstream_w, observer.client),
                self._pump_to_tls(upstream_r, stream, observer.server),
            )
            observer.eof()
            STATS["exchanges"] += observer.exchanges
        finally:
            STATS["active"] -= 1
            for writer in (client_w, upstream_w):
                close(writer)

    async def _answer_locally(
        self, stream: SslStream, observer, cid: str, peer: str, port: int,
        head: bytes, target: bytes, payload, reason: str,
        content_type: str = "application/json"
    ) -> None:
        """Answer a request here instead of forwarding it.

        Either a rewritten catalogue entry or a served asset. Both are
        deliberate and both shadow something real, so each one is logged
        with the rule that matched.
        """
        body = payload if isinstance(payload, bytes) else payload.encode()
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: " + content_type.encode() + b"\r\n"
            b"Cache-Control: no-store, no-cache, must-revalidate\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        STATS["answered_locally"] += 1
        self.log.record(
            {"event": "answered", "conn": cid, "peer": peer, "port": port,
             "target": target.decode("latin-1"), "bytes": len(body),
             "reason": reason},
            line=(f"{clock()} {cid} ++ {reason}: answered "
                  f"{printable(target.decode('latin-1'))} locally "
                  f"({len(body)}B)"),
        )
        self._observe(observer.client, head)
        self._observe(observer.server, response)
        try:
            await stream.write(response)
        except (ssl.SSLError, OSError):
            pass
        observer.eof()
        await stream.shutdown()
        close(stream.writer)

    async def _pump_from_tls(self, stream: SslStream, writer, observe) -> None:
        try:
            while True:
                data = await stream.read()
                if not data:
                    break
                self._observe(observe, data)
                writer.write(data)
                await writer.drain()
        except (ssl.SSLError, OSError, asyncio.TimeoutError):
            pass
        finally:
            try:
                if writer.can_write_eof():
                    writer.write_eof()
            except OSError:
                pass

    async def _pump_to_tls(self, reader, stream: SslStream, observe) -> None:
        timeout = self.cfg.idle_timeout or None
        try:
            while True:
                if timeout:
                    data = await asyncio.wait_for(reader.read(READ_SIZE), timeout)
                else:
                    data = await reader.read(READ_SIZE)
                if not data:
                    break
                self._observe(observe, data)
                await stream.write(data)
        except (ssl.SSLError, OSError, asyncio.TimeoutError):
            pass
        finally:
            # Closing the device side also releases the other pump, which
            # is parked on a read the radio will never satisfy.
            await stream.shutdown()
            close(stream.writer)

    @staticmethod
    def _observe(observe, data: bytes) -> None:
        """A parser fault must never cost the device its catalogue."""
        try:
            observe(data)
        except Exception as exc:  # noqa: BLE001 - logging must not be fatal
            STATS["last_error"] = f"observer: {type(exc).__name__}: {exc}"

    async def _pump(self, reader, writer, observe) -> None:
        timeout = self.cfg.idle_timeout or None
        try:
            while True:
                if timeout:
                    data = await asyncio.wait_for(reader.read(READ_SIZE), timeout)
                else:
                    data = await reader.read(READ_SIZE)
                if not data:
                    break
                self._observe(observe, data)
                writer.write(data)
                await writer.drain()
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            try:
                if writer.can_write_eof():
                    writer.write_eof()
            except OSError:
                pass


def set_nodelay(writer) -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


def close(writer) -> None:
    if writer is None:
        return
    try:
        writer.close()
    except OSError:
        pass


class HandshakeAborted(Exception):
    """The client went away mid-handshake.

    Emphatically not a refusal: devices abandon connections all the time.
    Counting these towards the revert budget would demote the listener for
    ordinary network noise.
    """


class SslStream:
    """Plaintext over a TLS session driven by memory BIOs.

    asyncio can terminate TLS on a listener directly, but it reports a
    refused handshake through _fatal_error, which drops anything that is
    an OSError - and ssl.SSLError is one. The refusal would vanish, and
    the refusal is the entire point of the probe. Driving the handshake
    here keeps the alert, whose name says whether the firmware checked a
    CA bundle, pinned a key, or simply disliked our ciphers.
    """

    def __init__(
        self, context: ssl.SSLContext, reader, writer, idle_timeout: int = 0
    ) -> None:
        self.idle_timeout = idle_timeout or None
        self.incoming = ssl.MemoryBIO()
        self.outgoing = ssl.MemoryBIO()
        self.sslobj = context.wrap_bio(
            self.incoming, self.outgoing, server_side=True
        )
        self.reader = reader
        self.writer = writer

    def feed(self, data: bytes) -> None:
        self.incoming.write(data)

    async def _flush(self) -> None:
        data = self.outgoing.read()
        if data:
            self.writer.write(data)
            await self.writer.drain()

    async def _pull(self) -> bool:
        if self.idle_timeout:
            chunk = await asyncio.wait_for(
                self.reader.read(READ_SIZE), self.idle_timeout
            )
        else:
            chunk = await self.reader.read(READ_SIZE)
        if not chunk:
            self.incoming.write_eof()
            return False
        self.incoming.write(chunk)
        return True

    async def handshake(self) -> None:
        while True:
            try:
                self.sslobj.do_handshake()
                break
            except ssl.SSLWantReadError:
                await self._flush()
                if not await self._pull():
                    raise HandshakeAborted("client closed during handshake")
        await self._flush()

    async def read(self) -> bytes:
        while True:
            try:
                return self.sslobj.read(READ_SIZE)
            except ssl.SSLWantReadError:
                await self._flush()
                if not await self._pull():
                    return b""
            except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                return b""

    async def write(self, data: bytes) -> None:
        self.sslobj.write(data)
        await self._flush()

    async def shutdown(self) -> None:
        """Tell the peer the response is over.

        The radio sends "Connection: Close" and then waits for the server
        to end the connection - that is how it knows the body is complete.
        Without a close_notify it waits forever, which looks exactly like
        the radio having frozen.
        """
        try:
            self.sslobj.unwrap()
        except (ssl.SSLError, OSError, ValueError):
            # unwrap also wants the peer's close_notify back; we only care
            # that ours is generated.
            pass
        try:
            await self._flush()
        except OSError:
            pass


class Listener:
    """One listening port, which may change mode while running.

    A probe listener that the device refuses demotes itself back to plain
    passthrough. That is the safety property: the experiment costs the
    radio a couple of failed requests, not its catalogue.
    """

    def __init__(
        self, tap: Tap, cfg: Config, log: Log, port: int, mode: str, upstream: int
    ) -> None:
        self.tap = tap
        self.cfg = cfg
        self.log = log
        self.port = port
        self.mode = mode
        self.upstream_port = upstream
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self.mode == "probe":
            self.tap.client_ctx = self.tap.client_ctx or build_client_context(self.cfg)
            self.tap.server_ctx = self.tap.server_ctx or build_server_context(self.cfg)
            self.server = await asyncio.start_server(
                functools.partial(
                    self.tap.handle_probe,
                    port=self.port,
                    upstream_port=self.upstream_port,
                    listener=self,
                ),
                host="0.0.0.0",
                port=self.port,
                reuse_address=True,
            )
            STATS["probe_state"] = f"probing on {self.port}"
        else:
            self.server = await asyncio.start_server(
                functools.partial(
                    self.tap.handle,
                    port=self.port,
                    mode=self.mode,
                    upstream_port=self.upstream_port,
                ),
                host="0.0.0.0",
                port=self.port,
                reuse_address=True,
            )

    async def demote(self, reason: str) -> None:
        if self.mode != "probe":
            return
        self.mode = PROBE_FALLBACK
        if self.server is not None:
            # Deliberately not awaiting wait_closed(): it waits for every
            # in-flight handler, including the one that called this.
            self.server.close()
        await self.start()
        STATS["probe_state"] = f"reverted to passthrough ({reason})"
        self.log.record(
            {"event": "probe_reverted", "port": self.port, "reason": reason},
            line=(f"{clock()} -- probe gave up on {self.port}: {reason}. "
                  f"Back to passthrough; browsing is unaffected."),
        )

    def close(self) -> None:
        if self.server is not None:
            self.server.close()


async def serve_status(reader, writer) -> None:
    try:
        try:
            await asyncio.wait_for(reader.read(4096), timeout=2)
        except asyncio.TimeoutError:
            pass
        body = json.dumps(STATS, indent=2)
        writer.write(
            (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body.encode())}\r\n"
                "Connection: close\r\n\r\n" + body
            ).encode()
        )
        await writer.drain()
    except OSError:
        pass
    finally:
        close(writer)


async def main() -> None:
    cfg = Config()
    log = Log(cfg.log_path, cfg.log_max_bytes)
    tap = Tap(cfg, log)

    loop = asyncio.get_running_loop()

    listeners = [
        Listener(tap, cfg, log, port, mode, upstream_port)
        for port, mode, upstream_port in cfg.listeners
    ]
    for listener in listeners:
        await listener.start()

    status_server = None
    if cfg.status_port:
        status_server = await asyncio.start_server(
            serve_status, host="0.0.0.0", port=cfg.status_port
        )

    listening = ", ".join(
        f"{p}/{m}" + (f"->{u}" if u != p else "") for p, m, u in cfg.listeners
    )
    log.record(
        {"event": "startup", "upstream": cfg.upstream,
         "listeners": listening, "log": cfg.log_path,
         "max_body": cfg.max_body},
        line=(f"{clock()} -- tap up: {listening} -> {cfg.upstream}, "
              f"log {cfg.log_path or 'stdout'}"),
    )

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.record({"event": "shutdown", **STATS}, line=f"{clock()} -- tap stopping")
    for listener in listeners:
        listener.close()
    if status_server is not None:
        status_server.close()


if __name__ == "__main__":
    asyncio.run(main())
