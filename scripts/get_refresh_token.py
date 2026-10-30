#!/usr/bin/env python3
"""One-time helper: get a Spotify refresh token for the weekly workflow.

Run this on your own computer, not in GitHub:
    python3 scripts/get_refresh_token.py

Before running, in your app on developer.spotify.com/dashboard, add this Redirect URI exactly:
    http://127.0.0.1:8888/callback

The script opens a Spotify login page, catches the redirect, and prints your refresh token.
Copy it into a GitHub secret named SPOTIFY_REFRESH_TOKEN. Never commit it to the repo.
"""
import base64
import getpass
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-top-read"

client_id = input("Spotify Client ID: ").strip()
client_secret = getpass.getpass("Spotify Client Secret (hidden): ").strip()
state = secrets.token_urlsafe(16)

auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
    "client_id": client_id,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPE,
    "state": state,
})

result = {}


class Callback(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("state", [""])[0] != state:
            result["error"] = "State mismatch. Try again."
        elif "error" in query:
            result["error"] = query["error"][0]
        else:
            result["code"] = query.get("code", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Done. You can close this tab and go back to the terminal." if "code" in result else "Something went wrong. Check the terminal."
        self.wfile.write(f"<p style='font:18px sans-serif'>{msg}</p>".encode())

    def log_message(self, *args):
        pass


print("\nOpening Spotify in your browser. If it doesn't open, visit:\n" + auth_url + "\n")
webbrowser.open(auth_url)
server = HTTPServer(("127.0.0.1", 8888), Callback)
while not result:
    server.handle_request()

if "error" in result:
    raise SystemExit("Authorization failed: " + result["error"])

data = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "code": result["code"],
    "redirect_uri": REDIRECT_URI,
}).encode()
auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
req = urllib.request.Request("https://accounts.spotify.com/api/token", data=data, method="POST", headers={
    "Authorization": f"Basic {auth}",
    "Content-Type": "application/x-www-form-urlencoded",
})
with urllib.request.urlopen(req) as resp:
    tokens = json.loads(resp.read())

print("\nYour refresh token (save it as the GitHub secret SPOTIFY_REFRESH_TOKEN):\n")
print(tokens["refresh_token"])
