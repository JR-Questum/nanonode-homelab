#!/usr/bin/env python3
"""Scheduled interrupts for the nanonode radio.

Managed by Ansible - deploy_radio_scheduler. Do not edit on the host.

News: fetches the newest VRT NWS bulletin shortly before the slot, then
pauses go-librespot, pushes the file into Liquidsoap's voice queue, waits
for the queue to drain, and resumes playback.

Weather: fetches Open-Meteo, has Ollama phrase it, synthesizes with
Piper, and plays it the same way. Skipped when nobody is listening.

DJ links: the AutoDJ writes a dj_queue row a full track ahead. This
generates and synthesizes the intro and writes the path back; the AutoDJ
pushes the clip itself when the track starts, so it ducks over the intro
rather than pausing.

The resume is driven by polling Liquidsoap's telnet rather than sleeping
for a guessed duration: clip length varies, and Liquidsoap knows exactly
when the voice source stops producing audio.
"""

from __future__ import annotations

import email.utils
import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import wave
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

log = logging.getLogger("scheduler")

NEWS_FILE = "news.mp3"
WEATHER_FILE = "weather.wav"
TTS_TEST_FILE = "tts_test.wav"
DJ_DIR = "dj"
QUEUE_POLL_SECONDS = 1.0
QUEUE_MAX_WAIT = 900

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes, abbreviated to what Belgium sees.
WMO = {
    0: "onbewolkt", 1: "overwegend zonnig", 2: "halfbewolkt", 3: "bewolkt",
    45: "mistig", 48: "mistig met rijm",
    51: "lichte motregen", 53: "motregen", 55: "dichte motregen",
    61: "lichte regen", 63: "regen", 65: "zware regen",
    66: "ijzel", 67: "zware ijzel",
    71: "lichte sneeuw", 73: "sneeuw", 75: "zware sneeuw",
    77: "sneeuwkorrels",
    80: "enkele buien", 81: "buien", 82: "zware buien",
    85: "sneeuwbuien", 86: "zware sneeuwbuien",
    95: "onweer", 96: "onweer met hagel", 99: "zwaar onweer met hagel",
}


class Telnet:
    """Liquidsoap's telnet server. One connection per command."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def command(self, line: str) -> str:
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            sock.sendall(f"{line}\nquit\n".encode())
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        return b"".join(chunks).decode("utf-8", "replace")


def http_post(url: str) -> bool:
    req = urllib.request.Request(
        url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as exc:
        log.error("POST %s failed: %s", url, exc)
        return False


def http_get_json(url: str, timeout: int = 20) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.error("GET %s failed: %s", url, exc)
        return None


def count_listeners(status_url: str, mount: str) -> int | None:
    """Listener count on the mount, or None if Icecast is unreachable.

    None is distinct from 0: an unreachable Icecast must not be read as
    'nobody is listening'.
    """
    stats = http_get_json(status_url, timeout=5)
    if stats is None:
        return None
    source = stats.get("icestats", {}).get("source")
    if source is None:
        return 0
    # Icecast returns a dict for one mount, a list for several.
    sources = source if isinstance(source, list) else [source]
    for entry in sources:
        if entry.get("listenurl", "").endswith(mount):
            return int(entry.get("listeners", 0))
    return 0


def stamp_voice(db: sqlite3.Connection) -> None:
    """Record that the station just spoke.

    The AutoDJ reads this to suppress a DJ link that would otherwise land
    straight after the news or weather.
    """
    with db:
        db.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES ('last_voice_at', datetime('now'), datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value, updated_at = excluded.updated_at"""
        )


# --- text generation -------------------------------------------------

# Piper spells abbreviations letter by letter, so expand anything an LLM
# might emit despite being told not to. Order matters: longer patterns
# first, or 'km' would match inside 'km/u'.
SPEECH_EXPANSIONS = [
    (r"\bkm\s*/\s*u(ur)?\b", "kilometer per uur"),
    (r"\bkm\b", "kilometer"),
    (r"\bm\s*/\s*s\b", "meter per seconde"),
    (r"\bmm\b", "millimeter"),
    (r"\bgr\.\b", "graden"),
    (r"(\d)\s*°\s*C\b", r"\1 graden"),
    (r"(\d)\s*°", r"\1 graden"),
    (r"\bpct\b", "procent"),
    (r"%", " procent"),
    (r"\bbv\.\b", "bijvoorbeeld"),
    (r"\bo\.a\.\b", "onder andere"),
]


def clean_for_speech(text: str) -> str:
    """Strip anything Piper would read aloud as punctuation or choke on.

    LLMs add markdown and emoji unprompted; Piper reads asterisks and
    hashes literally and spells abbreviations letter by letter. Accented
    Latin characters must survive, so emoji are removed by Unicode
    category rather than by ASCII filtering.
    """
    text = re.sub(r"[*_#`>|]", " ", text)
    text = re.sub(r"^\s*[-\u2022]\s*", "", text, flags=re.MULTILINE)
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cn"))
    for pattern, replacement in SPEECH_EXPANSIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate(prompt: str, cfg: dict) -> str | None:
    """Ask Ollama for text. Returns None on failure or an unusable reply."""
    payload = json.dumps({
        "model": cfg["ollama_model"],
        "prompt": prompt,
        "stream": False,
        # num_thread must be passed per-request: llama.cpp reads the
        # HOST's core count, not the cgroup limit, and oversubscribing
        # the LXC's cpuset costs a 20x slowdown.
        "options": {"num_thread": cfg["ollama_num_thread"]},
    }).encode()

    req = urllib.request.Request(
        f"{cfg['ollama_api']}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=cfg["ollama_timeout"]) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.error("ollama request failed: %s", exc)
        return None

    text = clean_for_speech(body.get("response", ""))
    elapsed = time.monotonic() - started

    if not text:
        log.warning("ollama returned nothing usable")
        return None
    if len(text.split()) > 60:
        log.warning("ollama reply too long (%d words), rejecting", len(text.split()))
        return None

    log.info("generated %d words in %.1fs: %s", len(text.split()), elapsed, text)
    return text


# --- weather ---------------------------------------------------------

def fetch_weather(cfg: dict) -> dict | None:
    params = urllib.parse.urlencode({
        "latitude": cfg["lat"],
        "longitude": cfg["lon"],
        "timezone": cfg["tz"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "forecast_hours": 4,
    })
    data = http_get_json(f"{OPEN_METEO}?{params}")
    if data is None or "current" not in data:
        return None

    cur = data["current"]
    hourly = data.get("hourly", {})
    codes = hourly.get("weather_code", [])[1:4]
    temps = hourly.get("temperature_2m", [])[1:4]
    rain = hourly.get("precipitation_probability", [])[1:4]

    return {
        "now_temp": round(cur.get("temperature_2m", 0)),
        "now_feels": round(cur.get("apparent_temperature", 0)),
        "now_desc": WMO.get(cur.get("weather_code"), "wisselvallig"),
        "wind": round(cur.get("wind_speed_10m", 0)),
        "later_desc": WMO.get(codes[-1], "wisselvallig") if codes else "wisselvallig",
        "later_temp": round(temps[-1]) if temps else None,
        "rain_chance": max(rain) if rain else None,
    }


def weather_prompt(w: dict, place: str) -> str:
    parts = [
        f"Nu in {place}: {w['now_desc']}, {w['now_temp']} graden",
        f"(gevoelstemperatuur {w['now_feels']})",
        f"wind {w['wind']} kilometer per uur",
        f"Straks: {w['later_desc']}",
    ]
    if w["later_temp"] is not None:
        parts.append(f"rond {w['later_temp']} graden")
    if w["rain_chance"] is not None:
        parts.append(f"kans op neerslag {w['rain_chance']} procent")

    return (
        "Je bent de radio-dj van een klein Vlaams radiostation. "
        "Breng het weerbericht hieronder in twee korte, speelse zinnen. "
        "Schrijf vlot Nederlands zoals je het zou zeggen, niet zoals je het zou "
        "schrijven.\n\n"
        "Regels:\n"
        "- Begin niet met een begroeting. Val meteen met de deur in huis.\n"
        "- Schrijf eenheden voluit: 'kilometer per uur', nooit 'km/u' of 'km/uur'.\n"
        "- Geen opsommingen, geen emoji, geen sterretjes, geen kopjes.\n"
        "- Maximaal 40 woorden. Noem de temperatuur.\n\n"
        + ". ".join(parts)
    )


def fallback_weather_text(w: dict, place: str) -> str:
    text = (
        f"Het weer in {place}: {w['now_desc']}, {w['now_temp']} graden. "
        f"Straks {w['later_desc']}"
    )
    if w["later_temp"] is not None:
        text += f", rond {w['later_temp']} graden"
    return text + "."


# --- DJ links --------------------------------------------------------

def dj_prompt(artists: str, title: str) -> str:
    return (
        "Je bent de radio-dj van een klein Vlaams radiostation. "
        "Kondig het volgende nummer aan in één korte, speelse zin van "
        "maximaal 20 woorden.\n\n"
        "Regels:\n"
        "- Begin niet met een begroeting.\n"
        "- Noem de artiest en de titel precies zoals hieronder gegeven.\n"
        "- Schrijf eenheden en afkortingen voluit.\n"
        "- Geen opsommingen, geen emoji, geen sterretjes, geen aanhalingstekens.\n"
        "- Verzin geen feiten die je niet zeker weet.\n\n"
        f"Artiest: {artists}\n"
        f"Titel: {title}"
    )


def fallback_dj_text(artists: str, title: str) -> str:
    return f"{title}, van {artists}."


def process_dj_queue(cfg: dict, db: sqlite3.Connection) -> None:
    """Generate and synthesize intros the AutoDJ has asked for.

    The AutoDJ writes a row a full track ahead, so there is time for a
    slow generation. It claims the clip itself when the track starts.
    """
    rows = db.execute(
        """SELECT id, track_uri, title, artists FROM dj_queue
           WHERE audio_path IS NULL AND played_at IS NULL
           ORDER BY id"""
    ).fetchall()

    for row in rows:
        text = generate(dj_prompt(row["artists"], row["title"]), cfg)
        if text is None:
            text = fallback_dj_text(row["artists"], row["title"])
            log.info("using fallback DJ text: %s", text)

        filename = f"{DJ_DIR}/link_{row['id']}.wav"
        dest = os.path.join(cfg["voice_dir"], filename)
        if not synthesize(text, dest, cfg):
            # Mark played so a persistently failing row is not retried
            # forever; the track simply gets no intro.
            with db:
                db.execute(
                    "UPDATE dj_queue SET played_at = datetime('now') WHERE id = ?",
                    (row["id"],),
                )
            continue

        with db:
            db.execute(
                "UPDATE dj_queue SET audio_path = ? WHERE id = ?",
                (os.path.join(cfg["voice_mount"], filename), row["id"]),
            )
        log.info("DJ link ready for %s - %s", row["artists"], row["title"])


def prune_dj_clips(cfg: dict, db: sqlite3.Connection) -> None:
    """Delete WAVs for rows already played, so /voice does not grow."""
    rows = db.execute(
        "SELECT id, audio_path FROM dj_queue "
        "WHERE played_at IS NOT NULL AND audio_path IS NOT NULL"
    ).fetchall()
    for row in rows:
        path = os.path.join(
            cfg["voice_dir"], DJ_DIR, os.path.basename(row["audio_path"])
        )
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("could not remove %s: %s", path, exc)
            continue
        with db:
            db.execute(
                "UPDATE dj_queue SET audio_path = NULL WHERE id = ?", (row["id"],)
            )


# --- speech ----------------------------------------------------------

def prepend_silence(path: str, seconds: float) -> None:
    """Insert leading silence so the duck completes before speech starts."""
    try:
        with wave.open(path, "rb") as src:
            params = src.getparams()
            frames = src.readframes(src.getnframes())
    except (wave.Error, OSError) as exc:
        log.warning("could not pad %s: %s", path, exc)
        return

    pad = b"\x00" * int(
        params.framerate * seconds * params.sampwidth * params.nchannels
    )
    tmp = path + ".pad"
    with wave.open(tmp, "wb") as dst:
        dst.setparams(params)
        dst.writeframes(pad + frames)
    os.replace(tmp, path)


def synthesize(text: str, dest: str, cfg: dict) -> bool:
    """Render text to a WAV via Piper. Writes atomically."""
    tmp = dest + ".part"
    env = {**os.environ, "OMP_NUM_THREADS": str(cfg["tts_threads"])}
    try:
        result = subprocess.run(
            ["piper", "--model", cfg["piper_model"], "--output_file", tmp],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.error("piper failed to run: %s", exc)
        return False

    if result.returncode != 0:
        log.error(
            "piper exited %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", "replace")[:400],
        )
        return False

    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        log.error("piper produced no audio")
        return False

    os.replace(tmp, dest)
    if cfg["tts_lead_in"] > 0:
        prepend_silence(dest, cfg["tts_lead_in"])
    log.info("synthesized %d chars to %s", len(text), dest)
    return True


# --- news ------------------------------------------------------------

def fetch_latest_bulletin(feed_url: str, dest: str, max_age_minutes: int) -> bool:
    """Download the newest enclosure. False if missing, stale or failed."""
    try:
        with urllib.request.urlopen(feed_url, timeout=30) as resp:
            root = ET.fromstring(resp.read())
    except (urllib.error.URLError, ET.ParseError, OSError) as exc:
        log.error("feed fetch failed: %s", exc)
        return False

    newest = None
    for item in root.iter("item"):
        enclosure = item.find("enclosure")
        pub = item.findtext("pubDate")
        if enclosure is None or not pub:
            continue
        try:
            when = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if newest is None or when > newest[0]:
            newest = (when, enclosure.get("url"), item.findtext("title"))

    if newest is None:
        log.error("no usable items in feed")
        return False

    when, url, title = newest
    age = datetime.now(timezone.utc) - when
    if age > timedelta(minutes=max_age_minutes):
        log.warning("newest bulletin is %s old, skipping", age)
        return False

    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(65536):
                out.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        log.error("bulletin download failed: %s", exc)
        return False

    # Rename only once complete: Liquidsoap must never see a partial file.
    os.replace(tmp, dest)
    log.info("fetched %r (%s, %d bytes)", title, when.isoformat(), os.path.getsize(dest))
    return True


# --- playback --------------------------------------------------------

def queue_pending(telnet: Telnet) -> bool | None:
    """True while the voice source is still producing audio.

    voice.queue lists only *pending* requests and reads empty while a clip
    is being decoded, so it cannot detect the end of playback.
    voice.playing is a custom command registered in radio.liq.
    """
    try:
        out = telnet.command("voice.playing")
    except OSError as exc:
        log.warning("telnet poll failed: %s", exc)
        return None

    for line in out.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line == "END":
            break
        if line in ("true", "false"):
            return line == "true"
    log.warning("unexpected voice.playing response: %r", out)
    return None


def wait_for_queue_empty(telnet: Telnet) -> None:
    deadline = time.monotonic() + QUEUE_MAX_WAIT
    # Give Liquidsoap a moment to pick the request up before polling.
    time.sleep(3)
    while time.monotonic() < deadline:
        pending = queue_pending(telnet)
        if pending is None:
            return          # telnet unreachable: resume rather than hang
        if not pending:
            return
        time.sleep(QUEUE_POLL_SECONDS)
    log.warning("queue did not drain within %ss, resuming anyway", QUEUE_MAX_WAIT)


def play_paused(cfg: dict, telnet: Telnet, db: sqlite3.Connection,
                filename: str) -> None:
    """Pause music, play a clip, wait for it to finish, resume."""
    host_path = os.path.join(cfg["voice_dir"], filename)
    if not os.path.exists(host_path):
        log.warning("%s not on disk, skipping slot", filename)
        return

    liq_path = os.path.join(cfg["voice_mount"], filename)

    log.info("pausing playback for %s", filename)
    http_post(f"{cfg['api']}/player/pause")

    try:
        reply = telnet.command(f"voice.push {liq_path}")
        log.info("pushed %s (telnet said %r)", filename, reply.strip().splitlines()[:1])
    except OSError as exc:
        log.error("telnet push failed: %s", exc)
        http_post(f"{cfg['api']}/player/resume")
        return

    stamp_voice(db)
    wait_for_queue_empty(telnet)

    log.info("%s finished, resuming playback", filename)
    http_post(f"{cfg['api']}/player/resume")


def do_weather(cfg: dict, telnet: Telnet, db: sqlite3.Connection) -> None:
    listeners = count_listeners(cfg["icecast_status"], cfg["mount"])
    if listeners == 0:
        log.info("nobody listening, skipping weather")
        return

    data = fetch_weather(cfg)
    if data is None:
        log.warning("no weather data, skipping slot")
        return

    text = generate(weather_prompt(data, cfg["place"]), cfg)
    if text is None:
        # Boring beats silent: a failed generation falls back to a
        # plain template rather than dropping the slot.
        text = fallback_weather_text(data, cfg["place"])
        log.info("using fallback text: %s", text)

    dest = os.path.join(cfg["voice_dir"], WEATHER_FILE)
    if synthesize(text, dest, cfg):
        play_paused(cfg, telnet, db, WEATHER_FILE)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    try:
        cfg = {
            "api": os.environ["SCHED_LIBRESPOT_API"].rstrip("/"),
            "icecast_status": os.environ["SCHED_ICECAST_STATUS"],
            "mount": os.environ["SCHED_MOUNT"],
            "voice_dir": os.environ["SCHED_VOICE_DIR"],
            "voice_mount": os.environ["SCHED_VOICE_MOUNT"],
            "feed": os.environ["SCHED_NEWS_FEED"],
            "piper_model": os.environ["SCHED_PIPER_MODEL"],
            "tts_lead_in": float(os.environ.get("SCHED_TTS_LEAD_IN", "0")),
            "tts_threads": int(os.environ.get("SCHED_TTS_THREADS", "2")),
            "ollama_api": os.environ["SCHED_OLLAMA_API"].rstrip("/"),
            "ollama_model": os.environ["SCHED_OLLAMA_MODEL"],
            "ollama_num_thread": int(os.environ.get("SCHED_OLLAMA_NUM_THREAD", "4")),
            "ollama_timeout": int(os.environ.get("SCHED_OLLAMA_TIMEOUT", "120")),
            "lat": os.environ["SCHED_WEATHER_LAT"],
            "lon": os.environ["SCHED_WEATHER_LON"],
            "tz": os.environ["SCHED_WEATHER_TZ"],
            "place": os.environ["SCHED_WEATHER_PLACE"],
            "db": os.environ["SCHED_DB"],
        }
        telnet = Telnet(
            os.environ["SCHED_TELNET_HOST"], int(os.environ["SCHED_TELNET_PORT"])
        )
    except KeyError as exc:
        log.error("missing required environment variable: %s", exc)
        return 2

    news_enabled = os.environ.get("SCHED_NEWS_ENABLED", "1") == "1"
    weather_enabled = os.environ.get("SCHED_WEATHER_ENABLED", "1") == "1"
    dj_enabled = os.environ.get("SCHED_DJ_ENABLED", "1") == "1"
    tts_test = os.environ.get("SCHED_TTS_TEST", "0") == "1"
    fetch_minute = int(os.environ.get("SCHED_NEWS_FETCH_MINUTE", "8"))
    play_minute = int(os.environ.get("SCHED_NEWS_PLAY_MINUTE", "10"))
    max_age = int(os.environ.get("SCHED_NEWS_MAX_AGE_MINUTES", "90"))
    dj_poll = int(os.environ.get("SCHED_DJ_POLL_SECONDS", "15"))
    weather_minutes = {
        int(m) for m in os.environ.get("SCHED_WEATHER_MINUTES", "30").split(",") if m
    }

    os.makedirs(os.path.join(cfg["voice_dir"], DJ_DIR), exist_ok=True)
    db = sqlite3.connect(cfg["db"], timeout=30)
    db.row_factory = sqlite3.Row

    log.info(
        "starting: news=%s weather=%s at %s dj=%s tts_test=%s model=%s place=%s",
        news_enabled, weather_enabled, sorted(weather_minutes), dj_enabled,
        tts_test, cfg["ollama_model"], cfg["place"],
    )

    last = {}
    last_dj_poll = 0.0

    while True:
        now = datetime.now()
        key = (now.date(), now.hour, now.minute)

        if news_enabled and now.minute == fetch_minute and last.get("fetch") != key:
            last["fetch"] = key
            fetch_latest_bulletin(
                cfg["feed"], os.path.join(cfg["voice_dir"], NEWS_FILE), max_age
            )

        if news_enabled and now.minute == play_minute and last.get("news") != key:
            last["news"] = key
            play_paused(cfg, telnet, db, NEWS_FILE)

        if weather_enabled and now.minute in weather_minutes \
                and last.get("weather") != key:
            last["weather"] = key
            do_weather(cfg, telnet, db)

        # THROWAWAY - TTS smoke test. Remove once no longer useful.
        if tts_test and now.minute == 45 and last.get("test") != key:
            last["test"] = key
            out = os.path.join(cfg["voice_dir"], TTS_TEST_FILE)
            if synthesize("Goeiemiddag, dit is nanonode radio.", out, cfg):
                telnet.command(f"voice.push {cfg['voice_mount']}/{TTS_TEST_FILE}")

        if dj_enabled and time.monotonic() - last_dj_poll > dj_poll:
            last_dj_poll = time.monotonic()
            try:
                process_dj_queue(cfg, db)
                prune_dj_clips(cfg, db)
            except sqlite3.Error as exc:
                log.error("dj queue error: %s", exc)

        time.sleep(5)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)