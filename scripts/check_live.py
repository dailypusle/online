#!/usr/bin/env python3
"""Check every YouTube live channel listed in live.html and write live-status.json.

The channel IDs are read straight from live.html (the lines that look like
channelId: "UC..."), so adding a channel to the page is enough: the next run
starts checking it automatically.

For each channel we ask YouTube three things:
  1. Is the channel streaming live right now?
  2. Is that stream allowed to be embedded on other websites?
  3. (confirmed with YouTube's oEmbed service)

A channel is hidden on live.html only after it fails 2 checks in a row, so one
temporary glitch does not remove a working channel. If YouTube cannot be
reached at all, the previous result is kept unchanged.
"""
import datetime
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML_FILE = ROOT / "live.html"
OUT_FILE = ROOT / "live-status.json"
HIDE_AFTER_MISSES = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+cb; SOCS=CAI",  # skips YouTube's cookie-consent page
}


def get(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.status, response.read().decode("utf-8", "replace")


def channel_ids():
    text = HTML_FILE.read_text(encoding="utf-8")
    found = re.findall(r'channelId:\s*"(UC[\w-]{22})"', text)
    return list(dict.fromkeys(found))  # unique, keeps order


def check(channel_id):
    """Returns (state, reason). state: live | blocked | offline | unknown."""
    try:
        _, page = get(f"https://www.youtube.com/channel/{channel_id}/live")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return "offline", "channel not found (check the channel ID)"
        return "unknown", f"YouTube answered HTTP {error.code}"
    except Exception as error:  # network trouble: do not judge the channel
        return "unknown", f"could not load the live page ({error})"

    if "ytInitialData" not in page:
        return "unknown", "YouTube returned a page without video data (consent or bot check)"

    canonical = re.search(
        r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', page
    )
    if not canonical:
        return "offline", "channel is not streaming"

    if '"isLiveNow":true' not in page and '"isLive":true' not in page:
        return "offline", "video is not live (ended or upcoming)"

    if '"playableInEmbed":false' in page:
        return "blocked", "the broadcaster does not allow embedding"

    video_id = canonical.group(1)
    oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={video_id}", safe=""
    )
    try:
        get(oembed)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return "blocked", "embedding is disabled (oEmbed refused)"
        if error.code == 404:
            return "offline", "video not found"
    except Exception:
        pass  # oEmbed is only a second opinion

    return "live", "ok"


def main():
    ids = channel_ids()
    if not ids:
        print("No channel IDs found in live.html. Nothing to do.")
        return

    try:
        old = json.loads(OUT_FILE.read_text(encoding="utf-8")).get("channels", {})
    except (FileNotFoundError, ValueError):
        old = {}

    new = {}
    for channel_id in ids:
        state, reason = check(channel_id)
        time.sleep(1)
        previous = old.get(channel_id)
        print(f"{channel_id}: {state} - {reason}")

        if state == "unknown":
            new[channel_id] = previous or {"status": "unknown", "available": True, "misses": 0}
            continue

        if state == "live":
            misses = 0
        else:
            misses = min((previous or {}).get("misses", 0) + 1, HIDE_AFTER_MISSES)

        new[channel_id] = {
            "status": state,
            "available": misses < HIDE_AFTER_MISSES,
            "misses": misses,
        }

    if new == old:
        print("No changes, live-status.json left as it is.")
        return

    payload = {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channels": new,
    }
    OUT_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Wrote live-status.json")


if __name__ == "__main__":
    main()
