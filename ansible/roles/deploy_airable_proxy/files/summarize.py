#!/usr/bin/env python3
"""Group a capture into bursts and fingerprint them.

Managed by Ansible - deploy_airable_proxy. Do not edit on the host.

    python3 summarize.py /srv/airable/logs/airable.jsonl

When the traffic is TLS and cannot be read, the byte counts are still
evidence. The device opens a fresh connection per request, so a button
press shows up as a burst of connections, and the bytes each one moved
are a fingerprint of the request and response inside it.

The TLS handshake contributes a constant to every connection - same
server, same certificate, same cipher - so differences between
fingerprints are differences in the payload underneath. Two connections
with the same fingerprint almost certainly carried the same request.

That is enough to tell which button press produced which request, and
roughly how much came back, without decrypting anything.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

# Connections opened within this many seconds of the previous one are
# treated as part of the same user action.
BURST_GAP = 5.0

CLOSE_EVENTS = ("tls_close", "raw_close", "http_close")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load(path: str) -> list[dict]:
    stream = sys.stdin if path == "-" else open(path, encoding="utf-8")
    with stream as fh:
        return [json.loads(line) for line in fh if line.strip()]


def split_sessions(records: list[dict]) -> list[list[dict]]:
    """A restart resets connection ids, so sessions must not be mixed."""
    sessions: list[list[dict]] = []
    for record in records:
        if record["event"] == "startup" or not sessions:
            sessions.append([])
        sessions[-1].append(record)
    return [s for s in sessions if any(r["event"] == "open" for r in s)]


def host_label(record: dict | None) -> str:
    """Short name for the host, when the ClientHello named one.

    The catalogue client sends no SNI but the asset client does, so the
    presence of a label is itself a signal about which stack made the
    request.
    """
    sni = (record or {}).get("sni") or ""
    return sni.split(".")[0] if sni else ""


def collapse(marks: list[str]) -> str:
    """767/1592 767/1592 767/1592 -> '767/1592 x3'."""
    out = []
    for mark, count in Counter(marks).most_common():
        out.append(f"{mark} x{count}" if count > 1 else mark)
    return "  ".join(out)


def report(session: list[dict], index: int, total: int) -> None:
    opens = [r for r in session if r["event"] == "open"]
    closes = {r["conn"]: r for r in session if r["event"] in CLOSE_EVENTS}
    exchanges = defaultdict(list)
    for r in session:
        if r["event"] == "exchange":
            exchanges[r["conn"]].append(r)

    conns = sorted(opens, key=lambda r: parse_ts(r["ts"]))
    bursts: list[list[dict]] = []
    for conn in conns:
        started = parse_ts(conn["ts"])
        gap = (
            (started - parse_ts(bursts[-1][-1]["ts"])).total_seconds()
            if bursts
            else None
        )
        if gap is not None and gap <= BURST_GAP:
            bursts[-1].append(conn)
        else:
            bursts.append([conn])

    started = next(
        (r["ts"] for r in session if r["event"] == "startup"), conns[0]["ts"]
    )
    plaintext = sum(len(v) for v in exchanges.values())
    ports = sorted({c["port"] for c in conns})

    if total > 1:
        print(f"=== session {index} of {total}, tap started "
              f"{parse_ts(started).strftime('%H:%M:%S')} ===")
    print(f"{len(conns)} connections, {len(bursts)} bursts, "
          f"{plaintext} readable HTTP exchanges")
    print(f"ports used by the device: {', '.join(str(p) for p in ports)}")
    print()
    print(f"{'burst':>5}  {'first seen':<10}  {'gap':>8}  {'n':>2}  "
          f"fingerprints (sent/received)")
    print(f"{'-' * 5}  {'-' * 10}  {'-' * 8}  {'-' * 2}  {'-' * 40}")

    where: dict[str, list[int]] = defaultdict(list)
    gaps: list[float] = []
    previous_end = None
    for number, burst in enumerate(bursts, 1):
        marks = []
        for conn in burst:
            close = closes.get(conn["conn"])
            if close:
                mark = f"{close['bytes_to_server']}/{close['bytes_to_client']}"
                label = host_label(close)
                if label:
                    mark = f"{mark} [{label}]"
            else:
                mark = "?/?"
            marks.append(mark)
            if number not in where[mark]:
                where[mark].append(number)
        begin = parse_ts(burst[0]["ts"])
        if previous_end is None:
            gap_text = "-"
        else:
            seconds = (begin - previous_end).total_seconds()
            gaps.append(seconds)
            gap_text = f"{seconds:.1f}s"
        previous_end = parse_ts(burst[-1]["ts"])
        print(f"{number:>5}  {begin.strftime('%H:%M:%S'):<10}  {gap_text:>8}  "
              f"{len(burst):>2}  {collapse(marks)}")

    shared = {m: b for m, b in where.items() if len(b) > 1 and m != "?/?"}
    print()
    if shared:
        print("Fingerprints appearing in more than one burst:")
        for mark, in_bursts in sorted(shared.items()):
            joined = ", ".join(str(b) for b in in_bursts)
            print(f"  {mark:<12} bursts {joined}")
        print()
        print("The same fingerprint in two bursts means the device sent the")
        print("same request both times.")
    elif len(bursts) > 1:
        print("No fingerprint repeats across bursts - every action produced a")
        print("different request.")

    if gaps:
        print()
        print(f"Longest silence between bursts: {max(gaps):.1f}s. Traffic that "
              f"only appears\nnext to an action is driven by that action, not "
              f"by a background poll.")

    if plaintext:
        print()
        print("Readable exchanges:")
        for conn in conns:
            for ex in exchanges.get(conn["conn"], []):
                print(f"  {ex['method']:6} {ex['status']} "
                      f"{ex['resp_bytes']:>7}B  {ex['url']}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    sessions = split_sessions(load(sys.argv[1]))
    if not sessions:
        print("No connections in this capture.")
        return 1
    for index, session in enumerate(sessions, 1):
        if index > 1:
            print()
        report(session, index, len(sessions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
