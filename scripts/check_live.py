
#!/usr/bin/env python3
"""Conservative YouTube live-channel checker for DailyPulse."""

import datetime
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import yt_dlp

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML_FILE = ROOT / "live.html"
OUT_FILE = ROOT / "live-status.json"

HIDE_AFTER_MISSES = 2
CHECK_DELAY = 2

YOUTUBE_API_KEY = ""  # Optional YouTube Data API key

# Only these explicit statuses count as confirmation that
# a channel's current live target is not broadcasting.
CONFIRMED_OFFLINE = {
    "not_live",
    "post_live",
    "was_live",
}


def channel_ids():
    html = HTML_FILE.read_text(encoding="utf-8")

    found = re.findall(
        r'channelId:\s*"(UC[\w-]{22})"',
        html,
    )

    return list(dict.fromkeys(found))


def find_live(data):
    """Search extracted YouTube information for an active live video."""

    if isinstance(data, list):
        for item in data:
            result = find_live(item)
            if result:
                return result
        return None

    if not isinstance(data, dict):
        return None

    if (
        data.get("id")
        and (
            data.get("is_live") is True
            or data.get("live_status") == "is_live"
        )
    ):
        return data

    entries = data.get("entries")

    if entries:
        for entry in entries:
            result = find_live(entry)
            if result:
                return result

    return None


def extract_live_video(channel_id):
    """Check the channel's live page without guessing offline status."""

    url = f"https://www.youtube.com/channel/{channel_id}/live"

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "ignoreerrors": False,
        "socket_timeout": 30,
        "retries": 3,
        "extractor_retries": 3,
        "cachedir": False,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("YouTube returned incomplete information")

    # First, look for an explicitly detected active broadcast.
    live = find_live(info)

    if live:
        video_id = live.get("id")

        if not video_id or len(video_id) != 11:
            raise RuntimeError("Invalid YouTube video ID")

        return {
            "state": "live",
            "videoId": video_id,
            "reason": "Active live broadcast detected",
        }

    # Only trust explicit offline information from a direct video result.
    # A missing playlist, empty entries, or missing metadata is UNKNOWN.
    if info.get("id") and info.get("live_status") in CONFIRMED_OFFLINE:
        return {
            "state": "offline",
            "videoId": None,
            "reason": (
                "YouTube explicitly reports: "
                + str(info.get("live_status"))
            ),
        }

    raise RuntimeError(
        "YouTube did not provide enough information "
        "to confirm live or offline status"
    )


def check_embedding(video_id):
    """Check embedding permission if an API key is configured."""

    if not YOUTUBE_API_KEY:
        return "unknown"

    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        "?part=status&id="
        + urllib.parse.quote(video_id)
        + "&key="
        + urllib.parse.quote(YOUTUBE_API_KEY)
    )

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DailyPulse/1.0"},
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        items = data.get("items", [])

        if not items:
            return "unknown"

        if items[0].get("status", {}).get("embeddable") is True:
            return "allowed"

        return "blocked"

    except Exception as error:
        print(f"Embedding check warning: {error}")
        return "unknown"


def check(channel_id):
    try:
        result = extract_live_video(channel_id)

        if result["state"] == "offline":
            return "offline", result["reason"], None

        video_id = result["videoId"]
        embedding = check_embedding(video_id)

        if embedding == "blocked":
            return (
                "blocked",
                "YouTube does not allow embedding this video",
                None,
            )

        return "live", result["reason"], video_id

    except Exception as error:
        return "unknown", str(error), None


def load_previous_status():
    try:
        data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        return data.get("channels", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    if not HTML_FILE.exists():
        print("ERROR: live.html was not found.")
        return

    ids = channel_ids()

    if not ids:
        print("ERROR: No YouTube channel IDs found in live.html.")
        return

    old = load_previous_status()
    new = {}

    print(f"Checking {len(ids)} YouTube channels...\n")

    counts = {
        "live": 0,
        "offline": 0,
        "unknown": 0,
        "blocked": 0,
    }

    for channel_id in ids:
        state, reason, video_id = check(channel_id)
        previous = old.get(channel_id, {})

        counts[state] += 1

        print(f"{channel_id}: {state} - {reason}")

        if state == "live":
            entry = {
                "status": "live",
                "available": True,
                "misses": 0,
                "videoId": video_id,
            }

        elif state == "offline":
            misses = min(
                previous.get("misses", 0) + 1,
                HIDE_AFTER_MISSES,
            )

            entry = {
                "status": "offline",
                "available": misses < HIDE_AFTER_MISSES,
                "misses": misses,
            }

        elif state == "blocked":
            entry = {
                "status": "blocked",
                "available": False,
                "misses": 0,
            }

        else:
            # Unknown is NOT offline.
            # Make previously hidden channels visible again so
            # old false-offline results do not keep hiding them.
            entry = {
                "status": "unknown",
                "available": True,
                "misses": 0,
            }

        new[channel_id] = entry

        time.sleep(CHECK_DELAY)

    payload = {
        "updatedAt": datetime.datetime.now(
            datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channels": new,
    }

    OUT_FILE.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("\nDailyPulse live check completed.")
    print(f"Total channels: {len(ids)}")
    print(f"Live: {counts['live']}")
    print(f"Offline: {counts['offline']}")
    print(f"Unknown: {counts['unknown']}")
    print(f"Blocked: {counts['blocked']}")
    print("Updated live-status.json")


if __name__ == "__main__":
    main()
