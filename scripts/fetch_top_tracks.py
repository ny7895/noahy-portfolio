#!/usr/bin/env python3
"""Fetch my top Spotify tracks and save them to data/top-tracks.json.

Runs weekly in GitHub Actions. Needs three repository secrets:
  SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN

Optional environment variables:
  TIME_RANGE  short_term (~4 weeks, default) | medium_term (~6 months) | long_term (~1 year)
  LIMIT       number of tracks, 1-50 (default 10)
  OUTPUT      output path (default data/top-tracks.json)

Uses only the Python standard library, so there is nothing to install.
If anything fails, the existing JSON file is left untouched.
"""
import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TOKEN_URL = "https://accounts.spotify.com/api/token"
TOP_URL = "https://api.spotify.com/v1/me/top/tracks"
VALID_RANGES = {"short_term", "medium_term", "long_term"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("top-tracks")


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        log.error("Missing %s. Add it under Settings > Secrets and variables > Actions.", name)
        sys.exit(1)
    return value


def request(req, attempts=4):
    """Send a request, retrying on rate limits (429) and server errors (5xx)."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            retryable = e.code == 429 or e.code >= 500
            if not retryable or attempt == attempts:
                log.error("HTTP %s from %s: %s", e.code, req.full_url.split("?")[0], body)
                raise
            wait = int(e.headers.get("Retry-After", 2 ** attempt))
            log.warning("HTTP %s, retrying in %ss (attempt %s/%s)", e.code, wait, attempt, attempts)
            time.sleep(wait)
        except urllib.error.URLError as e:
            if attempt == attempts:
                log.error("Network error: %s", e.reason)
                raise
            log.warning("Network error (%s), retrying (attempt %s/%s)", e.reason, attempt, attempts)
            time.sleep(2 ** attempt)


def get_access_token(client_id, client_secret, refresh_token):
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST", headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    payload = request(req)
    if payload.get("refresh_token") and payload["refresh_token"] != refresh_token:
        log.warning("Spotify issued a new refresh token. If future runs fail with 'invalid_grant', "
                    "run scripts/get_refresh_token.py again and update the secret.")
    return payload["access_token"]


def pick_image(images):
    """Prefer the ~300px album image; fall back to whatever exists."""
    if not images:
        return None
    images = sorted(images, key=lambda i: i.get("width") or 0)
    for img in images:
        if (img.get("width") or 0) >= 200:
            return img["url"]
    return images[-1]["url"]


def simplify(item, rank):
    album = item.get("album") or {}
    return {
        "rank": rank,
        "name": item.get("name", "Unknown track"),
        "artists": [a.get("name", "") for a in item.get("artists", [])],
        "album": album.get("name", ""),
        "image": pick_image(album.get("images")),
        "url": (item.get("external_urls") or {}).get("spotify"),
        "duration_ms": item.get("duration_ms"),
    }


def main():
    client_id = env("SPOTIFY_CLIENT_ID", required=True)
    client_secret = env("SPOTIFY_CLIENT_SECRET", required=True)
    refresh_token = env("SPOTIFY_REFRESH_TOKEN", required=True)
    time_range = env("TIME_RANGE", "short_term")
    limit = int(env("LIMIT", "10"))
    output = env("OUTPUT", "data/top-tracks.json")

    if time_range not in VALID_RANGES:
        log.error("TIME_RANGE must be one of %s, got %r", sorted(VALID_RANGES), time_range)
        sys.exit(1)
    limit = max(1, min(limit, 50))

    log.info("Refreshing access token")
    token = get_access_token(client_id, client_secret, refresh_token)

    log.info("Fetching top %s tracks (%s)", limit, time_range)
    url = f"{TOP_URL}?{urllib.parse.urlencode({'time_range': time_range, 'limit': limit})}"
    payload = request(urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}))
    items = payload.get("items") or []

    # Safeguard: never replace last week's list with an empty one.
    if not items:
        log.warning("Spotify returned no tracks. Keeping the existing %s.", output)
        return

    result = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "range": time_range,
        "tracks": [simplify(item, i + 1) for i, item in enumerate(items)],
    }

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    tmp = output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, output)  # atomic write: no half-written file if something breaks
    log.info("Saved %s tracks to %s. #1 is %s by %s", len(items), output,
             result["tracks"][0]["name"], ", ".join(result["tracks"][0]["artists"]))


if __name__ == "__main__":
    main()
