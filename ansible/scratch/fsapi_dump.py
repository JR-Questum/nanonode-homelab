#!/usr/bin/env python3
"""Dump what the radio itself believes about what it is playing.

    python3 fsapi_dump.py 10.10.61.20 --out nanonode.json
    python3 fsapi_dump.py 10.10.61.20 --out stubru.json
    python3 fsapi_dump.py --diff nanonode.json stubru.json

The proxy can only show what crosses the network. This shows what the
device kept. If a slogan exists in a node here while the screen says
"Not specified", the display is a rendering problem; if no node holds it
for the local station but one does for a catalogued one, the difference
says exactly which field the firmware never fills in.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# Nodes worth asking about. Unknown ones answer FS_NODE_DOES_NOT_EXIST,
# which is itself informative, so guesses are cheap.
NODES = [
    "netRemote.play.info.name",
    "netRemote.play.info.text",
    "netRemote.play.info.artist",
    "netRemote.play.info.album",
    "netRemote.play.info.description",
    "netRemote.play.info.slogan",
    "netRemote.play.info.graphicUri",
    "netRemote.play.info.providerName",
    "netRemote.play.status",
    "netRemote.play.errorStr",
    "netRemote.play.serviceIds.ecc",
    "netRemote.play.serviceIds.dabService",
    "netRemote.nav.state",
    "netRemote.nav.status",
    "netRemote.nav.numItems",
    "netRemote.nav.depth",
    "netRemote.sys.mode",
    "netRemote.sys.info.friendlyName",
    "netRemote.sys.caps.volumeSteps",
]

LISTS = [
    ("netRemote.nav.presets", 20),
    ("netRemote.nav.list", 30),
]


def call(host: str, pin: str, verb: str, node: str, extra: str = "") -> str:
    url = f"http://{host}/fsapi/{verb}/{node}?pin={pin}{extra}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return f"<httpError code='{exc.code}'/>"
    except (urllib.error.URLError, OSError) as exc:
        return f"<netError>{exc}</netError>"


def parse_value(xml_text: str) -> tuple[str, str]:
    """Return (status, value) from an fsapiResponse."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "PARSE_ERROR", xml_text[:120]
    status = (root.findtext("status") or "?").strip()
    value = root.find("value")
    if value is None:
        return status, ""
    for child in value:
        return status, (child.text or "").strip()
    return status, ""


def parse_list(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.findall("item"):
        entry = {"key": item.get("key", "")}
        for field in item.findall("field"):
            name = field.get("name", "?")
            text = ""
            for child in field:
                text = (child.text or "").strip()
            entry[name] = text
        out.append(entry)
    return out


def dump(host: str, pin: str) -> dict:
    result: dict = {"host": host, "nodes": {}, "lists": {}}
    for node in NODES:
        status, value = parse_value(call(host, pin, "GET", node))
        result["nodes"][node] = {"status": status, "value": value}
        flag = "" if status == "FS_OK" else f"   [{status}]"
        print(f"  {node:42} {value!r}{flag}")
    for node, limit in LISTS:
        xml_text = call(host, pin, "LIST_GET_NEXT", f"{node}/-1",
                        f"&maxItems={limit}")
        items = parse_list(xml_text)
        result["lists"][node] = items
        print(f"\n  {node}: {len(items)} item(s)")
        for item in items:
            rendered = "  ".join(f"{k}={v!r}" for k, v in item.items())
            print(f"    {rendered}")
    return result


def diff(left_path: str, right_path: str) -> int:
    left = json.load(open(left_path))
    right = json.load(open(right_path))
    print(f"{'node':42} {'A':<28} B")
    print("-" * 100)
    changed = 0
    for node in sorted(set(left["nodes"]) | set(right["nodes"])):
        a = left["nodes"].get(node, {}).get("value", "<absent>")
        b = right["nodes"].get(node, {}).get("value", "<absent>")
        if a != b:
            changed += 1
            print(f"{node:42} {a[:26]!r:<28} {b[:60]!r}")
    print()
    print(f"{changed} node(s) differ. Anything holding a slogan or description")
    print("in one dump but not the other is the field the firmware never fills.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host", nargs="?")
    ap.add_argument("--pin", default="1234")
    ap.add_argument("--out")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    args = ap.parse_args()

    if args.diff:
        return diff(*args.diff)
    if not args.host:
        ap.error("give a host, or --diff two saved dumps")

    result = dump(args.host, args.pin)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
