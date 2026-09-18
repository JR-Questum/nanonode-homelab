#!/usr/bin/env python3
"""Keep the radio's station artwork pointing at the current Spotify cover.

Managed by Ansible - deploy_airable_artwork. Do not edit on the host.

go-librespot reports the playing track, album cover URL included. This
fetches that image and writes it where the Airable tap serves the station
logo from, so selecting the station shows the album that is playing.

Worth knowing before expecting too much: the M-9000S fetches the logo once
per station selection and never again during playback. The cover is
therefore a snapshot from the moment the station was selected, not a live
display. Track text is different - that arrives over ICY in the audio
stream and does update.

Reads configuration from the environment:
    ARTWORK_API         go-librespot base URL
    ARTWORK_DEST        image file to write
    ARTWORK_STATE       file remembering the last URL fetched
    ARTWORK_MAX_BYTES   refuse anything larger
    ARTWORK_TIMEOUT     seconds per HTTP request
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request

log = logging.getLogger("artwork")

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


def get(url: str, timeout: int) -> tuple[bytes, str]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "").split(";")[0]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s"
    )
    api = os.environ.get("ARTWORK_API", "http://127.0.0.1:3678")
    dest = os.environ.get("ARTWORK_DEST", "")
    state = os.environ.get("ARTWORK_STATE", "")
    max_bytes = int(os.environ.get("ARTWORK_MAX_BYTES", "2097152"))
    timeout = int(os.environ.get("ARTWORK_TIMEOUT", "10"))

    if not dest:
        log.error("ARTWORK_DEST is required")
        return 2

    try:
        raw, _ = get(f"{api}/status", timeout)
        status = json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Spotify not connected, or go-librespot restarting. Leaving the
        # previous cover in place beats blanking the display.
        log.info("no status from %s (%s), leaving artwork alone", api, exc)
        return 0

    track = status.get("track") or {}
    url = track.get("album_cover_url") or ""
    if not url:
        log.info("nothing playing, leaving artwork alone")
        return 0

    previous = ""
    if state and os.path.exists(state):
        with open(state, encoding="utf-8") as fh:
            previous = fh.read().strip()
    if url == previous and os.path.exists(dest):
        return 0

    try:
        blob, content_type = get(url, timeout)
    except (urllib.error.URLError, OSError) as exc:
        log.warning("could not fetch %s: %s", url, exc)
        return 0

    if content_type and content_type not in ALLOWED_TYPES:
        log.warning("refusing %s from %s", content_type, url)
        return 0
    if len(blob) > max_bytes:
        log.warning("refusing %d bytes from %s", len(blob), url)
        return 0

    # Written via a temporary file in the same directory: the tap reads
    # this path on every request, and a half-written image would be served.
    temporary = f"{dest}.new"
    with open(temporary, "wb") as fh:
        fh.write(blob)
    os.replace(temporary, dest)
    if state:
        with open(state, "w", encoding="utf-8") as fh:
            fh.write(url)

    log.info("artwork updated: %s (%d bytes) <- %s",
             track.get("album_name", "?"), len(blob), url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
