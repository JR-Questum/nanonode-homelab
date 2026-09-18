-- Managed by Ansible - deploy_playlist_aggregator.
-- Applied idempotently on every run; safe to re-execute.
--
-- NOTE: no ALTER TABLE here. SQLite has no ALTER TABLE ... IF NOT EXISTS,
-- so column additions are guarded in aggregate.py's connect() instead.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    uri            TEXT PRIMARY KEY,          -- spotify:track:...
    title          TEXT NOT NULL,
    artists        TEXT NOT NULL,             -- comma-joined, display only
    album          TEXT,
    duration_ms    INTEGER NOT NULL,
    explicit       INTEGER NOT NULL DEFAULT 0,
    is_local       INTEGER NOT NULL DEFAULT 0,
    first_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    banned         INTEGER NOT NULL DEFAULT 0,
    banned_at      TEXT
);

-- Normalised artists, so per-artist rules do not depend on parsing the
-- display string above.
CREATE TABLE IF NOT EXISTS artists (
    id    TEXT PRIMARY KEY,                   -- Spotify artist ID
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS track_artists (
    track_uri  TEXT NOT NULL REFERENCES tracks(uri) ON DELETE CASCADE,
    artist_id  TEXT NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,              -- 0 = primary artist
    PRIMARY KEY (track_uri, artist_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id             TEXT PRIMARY KEY,          -- Spotify playlist ID
    name           TEXT NOT NULL,             -- local label from inventory
    remote_name    TEXT,                      -- name as Spotify reports it
    snapshot_id    TEXT,                      -- changes when playlist edits
    last_synced_at TEXT,
    track_count    INTEGER
    -- 'kind' column added by connect(); 'general' or 'kids'
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id  TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_uri    TEXT NOT NULL REFERENCES tracks(uri) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, track_uri)
);

-- Every play, appended. The 168-hour non-repeat rule reads this.
-- Deliberately no foreign key to tracks: a track dropped from every
-- playlist must not have its history cascade-deleted, which would
-- silently reopen it for immediate replay.
CREATE TABLE IF NOT EXISTS plays (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    track_uri  TEXT NOT NULL,
    played_at  TEXT NOT NULL DEFAULT (datetime('now')),
    source     TEXT NOT NULL DEFAULT 'autodj' -- autodj | request | manual
);

-- Runtime settings. Phase 6's API writes these; the AutoDJ reads them on
-- every selection so a toggle takes effect immediately.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO settings (key, value) VALUES ('child_mode', '0');
INSERT OR IGNORE INTO settings (key, value) VALUES ('autodj_enabled', '1');

CREATE INDEX IF NOT EXISTS idx_plays_track_time ON plays(track_uri, played_at);
CREATE INDEX IF NOT EXISTS idx_plays_time       ON plays(played_at);
CREATE INDEX IF NOT EXISTS idx_tracks_explicit  ON tracks(explicit, banned);
CREATE INDEX IF NOT EXISTS idx_pl_tracks_track  ON playlist_tracks(track_uri);

-- Candidate view: everything eligible right now.
CREATE VIEW IF NOT EXISTS eligible_tracks AS
SELECT t.*,
       (SELECT MAX(played_at) FROM plays p WHERE p.track_uri = t.uri) AS last_played_at
FROM tracks t
WHERE t.banned = 0
  AND t.is_local = 0;