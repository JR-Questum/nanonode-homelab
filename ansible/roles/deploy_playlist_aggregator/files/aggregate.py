#!/usr/bin/env python3
"""Aggregate Spotify playlists into SQLite.

Managed by Ansible - deploy_playlist_aggregator. Do not edit on the host.

Reads configuration from the environment:
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
    AGGREGATOR_DB          path to the SQLite database
    AGGREGATOR_SCHEMA      path to schema.sql
    AGGREGATOR_PLAYLISTS   JSON list of {"id":..., "name":..., "kind":...}
    AGGREGATOR_FORCE       "1" to ignore snapshot_id and resync everything
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PAGE_SIZE = 100
MAX_RETRIES = 5

log = logging.getLogger("aggregator")


class SpotifyError(RuntimeError):
    pass


def request(url: str, headers: dict, data: bytes | None = None) -> dict:
    """Perform a request, honouring 429 Retry-After and retrying on 5xx."""
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Retry-After is in seconds and must be obeyed; ignoring
                # it escalates to a longer ban.
                wait = int(exc.headers.get("Retry-After", "5")) + 1
                log.warning("rate limited, sleeping %ss", wait)
                time.sleep(wait)
                continue
            if 500 <= exc.code < 600 and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning("HTTP %s, retrying in %ss", exc.code, wait)
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", "replace")[:500]
            raise SpotifyError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                log.warning("network error (%s), retrying in %ss", exc.reason, wait)
                time.sleep(wait)
                continue
            raise SpotifyError(f"network failure for {url}: {exc.reason}") from exc
    raise SpotifyError(f"gave up after {MAX_RETRIES} attempts: {url}")


def get_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange a refresh token for a short-lived access token.

    Client credentials cannot read playlist items since Spotify's
    February 2026 migration, so the authorization-code flow is required.
    The refresh token is long-lived but revocable: a password change or
    removing the app from connected apps surfaces as HTTP 400 here.
    """
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    payload = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    result = request(
        TOKEN_URL,
        {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
    )
    return result["access_token"]


def fetch_playlist_meta(token: str, playlist_id: str) -> dict:
    url = f"{API}/playlists/{playlist_id}?fields=name,snapshot_id"
    return request(url, {"Authorization": f"Bearer {token}"})


def fetch_playlist_tracks(token: str, playlist_id: str) -> list[dict]:
    """Page through a playlist.

    Spotify's February 2026 migration replaced /playlists/{id}/tracks with
    /playlists/{id}/items and renamed the per-entry key from 'track' to
    'item'. The old endpoint returns 403, not 404.
    """
    fields = (
        "next,items(item(uri,name,duration_ms,explicit,is_local,"
        "album(name),artists(id,name)))"
    )
    url = (
        f"{API}/playlists/{playlist_id}/items"
        f"?limit={PAGE_SIZE}&fields={urllib.parse.quote(fields)}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    items: list[dict] = []
    while url:
        page = request(url, headers)
        items.extend(page.get("items", []))
        url = page.get("next")
    return items


def connect(db_path: str, schema_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    with open(schema_path, encoding="utf-8") as handle:
        conn.executescript(handle.read())

    # SQLite has no ALTER TABLE ... IF NOT EXISTS, so added columns are
    # applied here rather than in schema.sql.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(playlists)")}
    if "kind" not in columns:
        log.info("migrating: adding playlists.kind")
        conn.execute(
            "ALTER TABLE playlists ADD COLUMN kind TEXT NOT NULL DEFAULT 'general'"
        )

    conn.commit()
    return conn


def sync_playlist(conn, token, entry, force):
    playlist_id = entry["id"]
    label = entry.get("name", playlist_id)
    kind = entry.get("kind", "general")

    meta = fetch_playlist_meta(token, playlist_id)
    snapshot = meta.get("snapshot_id")

    row = conn.execute(
        "SELECT snapshot_id, kind FROM playlists WHERE id = ?", (playlist_id,)
    ).fetchone()
    if row and row["snapshot_id"] == snapshot and row["kind"] == kind and not force:
        log.info("%s: unchanged (snapshot %s), skipping", label, (snapshot or "")[:12])
        return 0

    items = fetch_playlist_tracks(token, playlist_id)
    log.info("%s: fetched %d items", label, len(items))

    seen = 0
    with conn:  # one transaction: a failure mid-playlist changes nothing
        conn.execute(
            """INSERT INTO playlists (id, name, remote_name, snapshot_id,
                                      last_synced_at, track_count, kind)
               VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name,
                   remote_name = excluded.remote_name,
                   snapshot_id = excluded.snapshot_id,
                   last_synced_at = excluded.last_synced_at,
                   track_count = excluded.track_count,
                   kind = excluded.kind""",
            (playlist_id, label, meta.get("name"), snapshot, len(items), kind),
        )

        # Membership is rebuilt; tracks and their history are not, so a
        # track removed from a playlist keeps its play history and bans.
        conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
        )

        for position, item in enumerate(items):
            track = item.get("item")
            if not track or not track.get("uri"):
                continue  # removed or unavailable in this market
            if track.get("is_local"):
                continue  # no playable URI
            uri = track["uri"]
            if not uri.startswith("spotify:track:"):
                continue  # episodes and other non-track items

            artists = track.get("artists") or []
            artist_names = ", ".join(a["name"] for a in artists if a.get("name"))

            conn.execute(
                """INSERT INTO tracks (uri, title, artists, album, duration_ms,
                                       explicit, is_local)
                   VALUES (?, ?, ?, ?, ?, ?, 0)
                   ON CONFLICT(uri) DO UPDATE SET
                       title = excluded.title,
                       artists = excluded.artists,
                       album = excluded.album,
                       duration_ms = excluded.duration_ms,
                       explicit = excluded.explicit,
                       last_seen_at = datetime('now')""",
                (
                    uri,
                    track.get("name") or "(unknown)",
                    artist_names,
                    (track.get("album") or {}).get("name"),
                    track.get("duration_ms") or 0,
                    1 if track.get("explicit") else 0,
                ),
            )

            for index, artist in enumerate(artists):
                if not artist.get("id"):
                    continue
                conn.execute(
                    """INSERT INTO artists (id, name) VALUES (?, ?)
                       ON CONFLICT(id) DO UPDATE SET name = excluded.name""",
                    (artist["id"], artist.get("name") or "(unknown)"),
                )
                conn.execute(
                    """INSERT INTO track_artists (track_uri, artist_id, position)
                       VALUES (?, ?, ?)
                       ON CONFLICT(track_uri, artist_id) DO UPDATE SET
                           position = excluded.position""",
                    (uri, artist["id"], index),
                )

            conn.execute(
                """INSERT INTO playlist_tracks (playlist_id, track_uri, position)
                   VALUES (?, ?, ?)
                   ON CONFLICT(playlist_id, track_uri) DO UPDATE SET
                       position = excluded.position""",
                (playlist_id, uri, position),
            )
            seen += 1

    log.info("%s: stored %d playable tracks", label, seen)
    return seen


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    try:
        client_id = os.environ["SPOTIFY_CLIENT_ID"]
        client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
        refresh_token = os.environ["SPOTIFY_REFRESH_TOKEN"]
        db_path = os.environ["AGGREGATOR_DB"]
        schema_path = os.environ["AGGREGATOR_SCHEMA"]
        playlists = json.loads(os.environ["AGGREGATOR_PLAYLISTS"])
    except KeyError as exc:
        log.error("missing required environment variable: %s", exc)
        return 2
    except json.JSONDecodeError as exc:
        log.error("AGGREGATOR_PLAYLISTS is not valid JSON: %s", exc)
        return 2

    if not playlists:
        log.warning("no playlists configured, nothing to do")
        return 0

    force = os.environ.get("AGGREGATOR_FORCE") == "1"

    conn = connect(db_path, schema_path)
    try:
        token = get_token(client_id, client_secret, refresh_token)
    except SpotifyError as exc:
        log.error("token refresh failed (token revoked?): %s", exc)
        return 1

    failures = 0
    total = 0
    for entry in playlists:
        try:
            total += sync_playlist(conn, token, entry, force)
        except SpotifyError as exc:
            log.error("%s: %s", entry.get("name", entry.get("id")), exc)
            failures += 1

    counts = conn.execute(
        "SELECT COUNT(*) AS n, SUM(explicit) AS e FROM tracks WHERE banned = 0"
    ).fetchone()
    log.info(
        "catalogue: %d tracks (%d explicit), %d synced this run, %d playlist failures",
        counts["n"] or 0,
        counts["e"] or 0,
        total,
        failures,
    )
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())