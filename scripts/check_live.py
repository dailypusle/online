
#!/usr/bin/env python3
"""Reliable YouTube live-channel checker for DailyPulse."""

import datetime
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

import yt_dlp

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML_FILE = ROOT / "live.html"
OUT_FILE = ROOT / "live-status.json"

HIDE_AFTER_MISSES = 2
CHECK_DELAY = 1

YOUTUBE_API_KEY = ""  # Optional: add a YouTube Data API key


def channel_ids():
    import re

    html = HTML_FILE.read_text(encoding="utf-8")
    found = re.findall(r'channelId:\s*"(UC[\w-]{22})"', html)

    return list(dict.fromkeys(found))


def extract_live_video(channel_id):
    """Find the actual live video using yt-dlp."""

    url = f"https://www.youtube.com/channel/{channel_id}/live"

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "ignoreerrors": True,
        "socket_timeout": 30,
        "retries": 2,
        "extractor_retries": 2,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("YouTube returned no stream information")

    def find_live(data):
        if not isinstance(data, dict):
            return None

        if data.get("id") and (
            data.get("is_live") is True
            or data.get("live_status") == "is_live"
        ):
            return data

        entries = data.get("entries")

        if entries:
            for entry in entries:
                result = find_live(entry)
                if result:
                    return result

        return None

    live = find_live(info)

    if live:
        video_id = live.get("id")

        if not video_id or len(video_id) != 11:
            raise RuntimeError("Invalid YouTube video ID")

        return {
            "state": "live",
            "videoId": video_id,
            "reason": "Active live broadcast found",
        }

    # A successfully extracted channel with no active live broadcast
    # is offline. Extraction failures are handled separately as unknown.
    return {
        "state": "offline",
        "videoId": None,
        "reason": "No active live broadcast found",
    }


def check_embedding(video_id):
    """Check embedding permission when a YouTube API key is available."""

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

        return (
            "allowed"
            if items[0].get("status", {}).get("embeddable") is True
            else "blocked"
        )

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
            return "blocked", "YouTube does not allow embedding", None

        return "live", result["reason"], video_id

    except Exception as error:
        return "unknown", f"YouTube check failed: {error}", None


def main():
    ids = channel_ids()

    if not ids:
        print("No channel IDs found in live.html.")
        return

    try:
        old_data = json.loads(
            OUT_FILE.read_text(encoding="utf-8")
        )
        old = old_data.get("channels", {})
    except (FileNotFoundError, ValueError):
        old = {}

    new = {}

    for channel_id in ids:
        state, reason, video_id = check(channel_id)
        previous = old.get(channel_id, {})

        print(f"{channel_id}: {state} - {reason}")

        if state == "unknown":
            # Preserve the last known result during network errors.
            new[channel_id] = previous or {
                "status": "unknown",
                "available": True,
                "misses": 0,
            }

            time.sleep(CHECK_DELAY)
            continue

        if state == "live":
            misses = 0
        else:
            misses = min(
                previous.get("misses", 0) + 1,
                HIDE_AFTER_MISSES,
            )

        entry = {
            "status": state,
            "available": misses < HIDE_AFTER_MISSES,
            "misses": misses,
        }

        # Never retain an old video ID for an ended or blocked stream.
        if state == "live" and video_id:
            entry["videoId"] = video_id

        new[channel_id] = entry

        time.sleep(CHECK_DELAY)

    if new == old:
        print("No changes. live-status.json remains unchanged.")
        return

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

    print("Successfully updated live-status.json")


if __name__ == "__main__":
    main()
