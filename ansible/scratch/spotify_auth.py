#!/usr/bin/env python3
"""THROWAWAY - one-time Spotify OAuth bootstrap. Delete after use.

Run on a machine with a browser:
    SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python3 spotify_auth.py

Prints a refresh token to store as vault_spotify_refreshtoken.
"""

import base64
import http.server
import json
import os
import secrets
import urllib.parse
import urllib.request
import webbrowser

CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT = "http://127.0.0.1:8080/callback"
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"

state = secrets.token_urlsafe(16)
code_holder = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if params.get("state", [None])[0] != state:
            self.wfile.write(b"State mismatch - aborted.")
            return
        if "code" in params:
            code_holder["code"] = params["code"][0]
            self.wfile.write(b"Authorised. You can close this tab.")
        else:
            self.wfile.write(f"Failed: {params}".encode())

    def log_message(self, *args):
        pass


auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "response_type": "code",
    "redirect_uri": REDIRECT,
    "scope": SCOPES,
    "state": state,
})

print(f"\nOpen this if a browser does not appear:\n{auth_url}\n")
webbrowser.open(auth_url)

server = http.server.HTTPServer(("127.0.0.1", 8080), Handler)
server.handle_request()

if "code" not in code_holder:
    raise SystemExit("no authorization code received")

basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
payload = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "code": code_holder["code"],
    "redirect_uri": REDIRECT,
}).encode()
req = urllib.request.Request(
    "https://accounts.spotify.com/api/token",
    data=payload,
    headers={
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    },
)
with urllib.request.urlopen(req) as resp:
    tokens = json.load(resp)

print("\n=== Add to vault as vault_spotify_refreshtoken ===")
print(tokens["refresh_token"])
print("==================================================\n")