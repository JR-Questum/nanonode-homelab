#!/usr/bin/env python3
"""AutoDJ: selects tracks from the nanonode catalogue and drives go-librespot.

Managed by Ansible - deploy_autodj. Do not edit on the host.

Control model, derived from go-librespot's observed event stream:

  - 'stopped' from play_origin 'go-librespot' means playback ran out:
    the Spotify queue is empty, so play the next track.
  - 'stopped' from any other origin means a human stopped playback:
    stand down until playback resumes.
  - 'playing' where uri != the URI we last requested means a track came
    from the Spotify queue (a Jam addition). Record it and let it run.
  - 'not_playing', 'will_play', 'paused', 'seek' and 'metadata' are
    mid-sequence or user-initiated and are never triggers.

DJ links: every 3-5 tracks the next track is chosen a full track early
and written to dj_queue. The scheduler generates and synthesizes the
intro; when the current track ends, the clip is pushed into Liquidsoap's
voice queue just before the track starts, so it ducks over the intro.

Listeners are polled from Icecast: zero listeners means nobody is tuned
in, so playback stops. The first listener starts it again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import sqlite3
import sys
import urllib.error
import urllib.request

import websockets

log = logging.getLogger("autodj")

COOLDOWN_SECONDS = 2.0


class Telnet:
    """Liquidsoap's telnet server. One connection per command."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def command(self, line: str) -> str | None:
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as sock:
                sock.sendall(f"{line}\nquit\n".encode())
                chunks = []
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
            return b"".join(chunks).decode("utf-8", "replace")
        except OSError as exc:
            log.warning("telnet command failed: %s", exc)
            return None


class Catalogue:
    """All database access."""

    def __init__(self, path: str, window_hours: int, kids_ratio: float):
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.window = f"-{window_hours} hours"
        self.kids_ratio = kids_ratio
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """dj_queue is owned by this daemon, so it creates it itself
        rather than depending on the aggregator having run."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS dj_queue (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_uri    TEXT NOT NULL,
                    title        TEXT NOT NULL,
                    artists      TEXT NOT NULL,
                    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
                    audio_path   TEXT,
                    played_at    TEXT
                )
            """)
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dj_pending "
                "ON dj_queue(played_at, audio_path)"
            )

    def setting(self, key: str, default: str = "0") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO settings (key, value, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = excluded.updated_at""",
                (key, value),
            )

    def spoke_within(self, minutes: int) -> bool:
        """True if the station spoke recently. News, weather and DJ links
        all stamp last_voice_at, so this suppresses back-to-back voice."""
        row = self.conn.execute(
            "SELECT 1 FROM settings WHERE key = 'last_voice_at' "
            "AND value > datetime('now', ?)",
            (f"-{minutes} minutes",),
        ).fetchone()
        return row is not None

    def _select(self, child_mode: int, kind: str | None, respect_window: bool):
        window_clause = """
          AND NOT EXISTS (
                SELECT 1 FROM plays p
                WHERE p.track_uri = t.uri
                  AND p.played_at > datetime('now', :window)
          )
        """ if respect_window else ""

        order = "RANDOM()" if respect_window else """
            (SELECT MAX(played_at) FROM plays p WHERE p.track_uri = t.uri)
                ASC NULLS FIRST, RANDOM()
        """

        sql = f"""
            SELECT t.uri, t.title, t.artists, t.duration_ms, t.explicit
            FROM tracks t
            WHERE t.banned = 0
              AND t.is_local = 0
              AND (:child_mode = 0 OR t.explicit = 0)
              AND EXISTS (
                    SELECT 1
                    FROM playlist_tracks pt
                    JOIN playlists pl ON pl.id = pt.playlist_id
                    WHERE pt.track_uri = t.uri
                      AND (:kind IS NULL OR pl.kind = :kind)
              )
              {window_clause}
            ORDER BY {order}
            LIMIT 1
        """
        return self.conn.execute(
            sql,
            {"child_mode": child_mode, "kind": kind, "window": self.window},
        ).fetchone()

    def next_track(self) -> sqlite3.Row | None:
        child_mode = 1 if self.setting("child_mode", "0") == "1" else 0

        kind = None
        if child_mode and random.random() < self.kids_ratio:
            kind = "kids"

        row = self._select(child_mode, kind, respect_window=True)

        if row is None and kind == "kids":
            log.info("kids pool exhausted, falling back to general")
            row = self._select(child_mode, None, respect_window=True)

        if row is None:
            log.info("non-repeat window exhausted, using least-recently-played")
            row = self._select(child_mode, kind, respect_window=False)

        return row

    def record_play(self, uri: str, source: str = "autodj") -> None:
        # No foreign key to tracks: a Jam addition may be anything at all.
        with self.conn:
            self.conn.execute(
                "INSERT INTO plays (track_uri, source) VALUES (?, ?)", (uri, source)
            )

    def enqueue_dj(self, row: sqlite3.Row) -> None:
        """Ask the scheduler for an intro for this track."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO dj_queue (track_uri, title, artists) VALUES (?, ?, ?)",
                (row["uri"], row["title"], row["artists"]),
            )
        log.info("requested DJ link for %s - %s", row["artists"], row["title"])

    def claim_dj_clip(self, uri: str) -> str | None:
        """Return a ready clip for this URI and mark it played, or None."""
        row = self.conn.execute(
            """SELECT id, audio_path FROM dj_queue
               WHERE track_uri = ? AND played_at IS NULL
                 AND audio_path IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (uri,),
        ).fetchone()
        if row is None:
            return None
        with self.conn:
            self.conn.execute(
                "UPDATE dj_queue SET played_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        return row["audio_path"]

    def expire_stale_dj(self, uri: str) -> None:
        """Drop unplayed requests for other tracks: the AutoDJ changed
        its mind, so their clips will never be used."""
        with self.conn:
            self.conn.execute(
                "UPDATE dj_queue SET played_at = datetime('now') "
                "WHERE played_at IS NULL AND track_uri != ?",
                (uri,),
            )


class Player:
    """go-librespot REST client."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _post(self, path: str, payload: dict | None = None) -> bool:
        data = json.dumps(payload).encode() if payload is not None else b"{}"
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            log.error("%s failed: HTTP %s %s", path, exc.code, exc.reason)
        except urllib.error.URLError as exc:
            log.error("%s failed: %s", path, exc.reason)
        return False

    def play(self, uri: str) -> bool:
        return self._post("/player/play", {"uri": uri})

    def pause(self) -> bool:
        return self._post("/player/pause")


def count_listeners(status_url: str, mount: str) -> int | None:
    """Listener count on the mount, or None if Icecast is unreachable.

    None is distinct from 0: an unreachable Icecast must not be read as
    'nobody is listening', which would silence a working station.
    """
    try:
        with urllib.request.urlopen(status_url, timeout=5) as resp:
            stats = json.load(resp).get("icestats", {})
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.warning("icecast status unreachable: %s", exc)
        return None

    source = stats.get("source")
    if source is None:
        return 0
    # Icecast returns a dict for one mount, a list for several.
    sources = source if isinstance(source, list) else [source]
    for entry in sources:
        if entry.get("listenurl", "").endswith(mount):
            return int(entry.get("listeners", 0))
    return 0


class AutoDJ:
    def __init__(self, catalogue, player, telnet, cfg):
        self.catalogue = catalogue
        self.player = player
        self.telnet = telnet
        self.cfg = cfg
        self.standing_down = False
        self.active = False
        self.last_play_at = 0.0
        self.current_uri: str | None = None
        self._idle_task: asyncio.Task | None = None

        # DJ link state: a track chosen one track early, and a countdown
        # of tracks until the next link.
        self.pending: sqlite3.Row | None = None
        self.until_link = random.randint(cfg["dj_min_gap"], cfg["dj_max_gap"])

    def enabled(self) -> bool:
        return self.catalogue.setting("autodj_enabled", "1") == "1"

    async def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        if active:
            log.info("listeners present, starting playback")
            await self.play_next("listener joined")
        else:
            log.info("no listeners, pausing playback")
            self._cancel_idle()
            self.player.pause()

    def _speak(self, clip_path: str) -> bool:
        """Push a clip into Liquidsoap's voice queue. It ducks the music
        rather than pausing it, so the link runs over the track intro."""
        reply = self.telnet.command(f"voice.push {clip_path}")
        if reply is None:
            return False
        self.catalogue.set_setting(
            "last_voice_at",
            self.catalogue.conn.execute("SELECT datetime('now')").fetchone()[0],
        )
        return True
    
    def _announce(self, row: sqlite3.Row) -> None:
        """Send ICY metadata so listeners see the track.

        Raw PCM from the FIFO has no tags, so Liquidsoap has nothing to
        forward to Icecast unless it is injected here. Newlines would
        terminate the telnet command, so they are stripped.
        """
        artist = row["artists"].replace("\n", " ").strip()
        title = row["title"].replace("\n", " ").strip()
        self.telnet.command(f"master.1.meta {artist} - {title}")
                
    async def play_next(self, reason: str) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now - self.last_play_at < COOLDOWN_SECONDS:
            log.debug("cooldown active, ignoring trigger (%s)", reason)
            return
        if not self.enabled():
            log.info("autodj disabled in settings, not selecting (%s)", reason)
            return
        if not self.active:
            log.debug("no listeners, not selecting (%s)", reason)
            return

        # A track chosen early for a DJ link takes precedence.
        row = self.pending or self.catalogue.next_track()
        self.pending = None
        if row is None:
            log.error("no eligible tracks at all - catalogue empty?")
            return

        if self.player.play(row["uri"]):
            self.current_uri = row["uri"]
            self.catalogue.record_play(row["uri"])
            self._announce(row)
        else:
            log.error("play command rejected for %s", row["uri"])

        # Speak the intro first: pushing before the play command means
        # the clip is already ducking as the track comes in.
        clip = self.catalogue.claim_dj_clip(row["uri"])
        if clip:
            if self.catalogue.spoke_within(self.cfg["suppress_minutes"]):
                log.info("station spoke recently, skipping DJ link")
            elif self._speak(clip):
                log.info("DJ link for %s - %s", row["artists"], row["title"])

        self.last_play_at = now
        log.info("playing %s - %s (%s)", row["artists"], row["title"], reason)
        if self.player.play(row["uri"]):
            self.current_uri = row["uri"]
            self.catalogue.record_play(row["uri"])
        else:
            log.error("play command rejected for %s", row["uri"])

    def _maybe_request_link(self) -> None:
        """Called when a track starts. Counts down, and on reaching zero
        chooses the NEXT track early so the scheduler has a full track's
        duration to generate and synthesize an intro for it."""
        if not self.cfg["dj_enabled"]:
            return
        self.until_link -= 1
        if self.until_link > 0:
            return

        self.until_link = random.randint(
            self.cfg["dj_min_gap"], self.cfg["dj_max_gap"]
        )
        row = self.catalogue.next_track()
        if row is None:
            return
        self.pending = row
        self.catalogue.expire_stale_dj(row["uri"])
        self.catalogue.enqueue_dj(row)

    def _cancel_idle(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _reclaim_after_idle(self) -> None:
        try:
            await asyncio.sleep(self.cfg["idle_seconds"])
        except asyncio.CancelledError:
            return
        log.info("session idle for %ss, resuming control", self.cfg["idle_seconds"])
        self.standing_down = False
        await self.play_next("idle timeout")

    async def handle(self, event: dict) -> None:
        kind = event.get("type")
        data = event.get("data") or {}
        origin = data.get("play_origin", "")
        ours = origin == "go-librespot"

        if kind == "playing":
            self._cancel_idle()
            uri = data.get("uri")

            # A track we did not request is playing under our own origin:
            # it came from the Spotify queue, i.e. a Jam addition.
            if ours and uri and uri != self.current_uri:
                log.info("queued track playing: %s", uri)
                self.current_uri = uri
                self.catalogue.record_play(uri, source="jam")

            if not ours:
                if not self.standing_down:
                    log.info("standing down: session taken by %r", origin)
                self.standing_down = True
            else:
                self.standing_down = False
                if not data.get("resume"):
                    self._maybe_request_link()
            return

        if kind == "stopped":
            if not ours:
                log.info("playback stopped by %r, standing down", origin)
                self.standing_down = True
                self._cancel_idle()
                return
            if self.standing_down:
                self._cancel_idle()
                self._idle_task = asyncio.create_task(self._reclaim_after_idle())
                return
            await self.play_next("track ended")
            return

        if kind == "will_play":
            # Insurance: disable_autoplay stops Spotify's recommender, but
            # if it ever slips through, override it with our own choice.
            if data.get("context_uri", "").startswith("spotify:station:"):
                log.warning("autoplay station detected, overriding")
                await self.play_next("autoplay override")
            return

        # not_playing, paused, seek, metadata, volume: never triggers.


async def poll_listeners(dj: AutoDJ, status_url: str, mount: str, interval: int):
    while True:
        count = await asyncio.to_thread(count_listeners, status_url, mount)
        if count is not None:
            await dj.set_active(count > 0)
        await asyncio.sleep(interval)


async def consume_events(dj: AutoDJ, ws_url: str):
    backoff = 1
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                log.info("connected to %s", ws_url)
                backoff = 1
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning("unparseable event: %.120s", raw)
                        continue
                    await dj.handle(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - daemon must not die
            log.warning("event stream lost (%s), reconnecting in %ss", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    try:
        db_path = os.environ["AUTODJ_DB"]
        api_url = os.environ["AUTODJ_API"]
        ws_url = os.environ["AUTODJ_WS"]
        status_url = os.environ["AUTODJ_ICECAST_STATUS"]
        mount = os.environ["AUTODJ_MOUNT"]
        telnet = Telnet(
            os.environ["AUTODJ_TELNET_HOST"], int(os.environ["AUTODJ_TELNET_PORT"])
        )
    except KeyError as exc:
        log.error("missing required environment variable: %s", exc)
        return 2

    cfg = {
        "idle_seconds": int(os.environ.get("AUTODJ_IDLE_SECONDS", "60")),
        "dj_enabled": os.environ.get("AUTODJ_DJ_ENABLED", "1") == "1",
        "dj_min_gap": int(os.environ.get("AUTODJ_DJ_MIN_GAP", "3")),
        "dj_max_gap": int(os.environ.get("AUTODJ_DJ_MAX_GAP", "5")),
        "suppress_minutes": int(os.environ.get("AUTODJ_VOICE_SUPPRESS_MINUTES", "10")),
    }
    window = int(os.environ.get("AUTODJ_WINDOW_HOURS", "168"))
    kids_ratio = float(os.environ.get("AUTODJ_KIDS_RATIO", "0.3"))
    poll_seconds = int(os.environ.get("AUTODJ_POLL_SECONDS", "10"))

    dj = AutoDJ(
        Catalogue(db_path, window, kids_ratio),
        Player(api_url),
        telnet,
        cfg,
    )

    log.info(
        "starting: window=%sh dj=%s gap=%s-%s suppress=%smin poll=%ss mount=%s",
        window, cfg["dj_enabled"], cfg["dj_min_gap"], cfg["dj_max_gap"],
        cfg["suppress_minutes"], poll_seconds, mount,
    )

    await asyncio.gather(
        consume_events(dj, ws_url),
        poll_listeners(dj, status_url, mount, poll_seconds),
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(0)