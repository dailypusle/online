#!/usr/bin/env python3
"""Fetch configured RSS/Atom feeds and create combined, deduplicated RSS files.

Sports category = all sports (set SPORTS_SOCCER_ONLY = True to keep only soccer).
Every sports story must have a real body of text and a large, sharp image.
"""
import calendar, hashlib, html, json, mimetypes, re
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from urllib.request import Request, urlopen
from io import BytesIO
import feedparser
from PIL import Image, ImageFilter, ImageStat

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "feeds.json"
OUT = ROOT / "feeds"
MAX_PER_SOURCE = 100
USER_AGENT = "DailyPulse/1.0 (+RSS reader; respectful polling)"
IMAGE_TIMEOUT = 8
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 225
# Edge-variance blur heuristic. This is an image-quality check, not an AI vision model.
MIN_SHARPNESS = 55.0
# Sources marked "require_body": true in feeds.json must include at least this much summary text.
MIN_BODY_CHARS = 60

# ---- Sports rules ----------------------------------------------------------
# False = show every sport. True = soccer stories only.
SPORTS_SOCCER_ONLY = False
# HD-class images: wide landscape photos only (about 1024x576 or larger).
SPORTS_MIN_IMAGE_WIDTH = 1000
SPORTS_MIN_IMAGE_HEIGHT = 560
# Every sports story needs a real body, not just a one-line teaser.
SPORTS_MIN_BODY_CHARS = 200
SPORTS_MIN_TITLE_CHARS = 20

SOCCER_RE = re.compile(
    r"\b(soccer|football|premier league|epl|la liga|laliga|serie a|bundesliga|ligue 1|"
    r"champions league|europa league|conference league|fa cup|carabao cup|efl|championship|"
    r"world cup|afcon|africa cup of nations|caf|uefa|fifa|npfl|nff|super eagles|super falcons|"
    r"mls|copa america|euro 20\d\d|nations league|transfer|striker|goalkeeper|midfielder|"
    r"defender|winger|penalty|referee|var|hat-trick|"
    r"arsenal|chelsea|liverpool|manchester united|man utd|manchester city|man city|tottenham|spurs|"
    r"newcastle|aston villa|west ham|everton|leicester|real madrid|barcelona|atletico madrid|"
    r"bayern|dortmund|psg|paris saint-germain|juventus|inter milan|ac milan|napoli|roma|"
    r"benfica|porto|ajax|celtic|rangers|al nassr|inter miami|enyimba|rangers international)\b",
    re.I,
)
# Anything that clearly belongs to another sport is rejected, even if the word "football" appears.
OTHER_SPORT_RE = re.compile(
    r"\b(nfl|super bowl|quarterback|touchdown|american football|college football|ncaa|"
    r"nba|wnba|mlb|nhl|baseball|basketball|ice hockey|cricket|ipl|rugby|tennis|wimbledon|"
    r"golf|pga|formula 1|formula one|f1|motogp|nascar|boxing|ufc|mma|wwe|wrestling|"
    r"athletics|olympics|cycling|tour de france|snooker|darts)\b",
    re.I,
)

IMAGE_CHECK_CACHE = {}
CATEGORIES = {"top", "nigeria", "world", "entertainment", "sports", "technology", "science", "business", "gaming", "fashion", "other"}
PREVIEW_CATEGORIES = ("top", "nigeria", "world", "business", "entertainment", "sports", "technology", "science")
PREVIEW_LIMIT = 25  # stories per category written to news-preview.json


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def canonical_url(url):
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return ""
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}]
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", urlencode(query), ""))
    except Exception:
        return ""


def text_html(value):
    # Escape untrusted source content so it remains text inside the generated XML.
    return html.escape(clean(value), quote=False)


SOCCER_TAG_RE = re.compile(r"\b(soccer|football|premier league|la liga|laliga|serie a|bundesliga|ligue 1|champions league|europa league|fa cup|afcon|world cup|transfers?)\b", re.I)
SOCCER_PATH_RE = re.compile(r"/(football|soccer)(/|-|$)", re.I)


def entry_tags(entry):
    """Category/section labels the site itself attached to the story (RSS <category> tags)."""
    terms = []
    for tag in entry.get("tags", []) or []:
        term = clean(tag.get("term") or tag.get("label"))
        if term:
            terms.append(term)
    return " | ".join(terms)


def is_soccer(title, description, soccer_only=False, tags="", link=""):
    """True if the story is soccer news.

    Order of trust: the site's own category tags and URL section first, then
    soccer-only sources, then keyword matching as a fallback.
    """
    path = urlparse(link).path
    if tags and SOCCER_TAG_RE.search(tags) and not OTHER_SPORT_RE.search(tags):
        return True
    if SOCCER_PATH_RE.search(path):
        return True
    if tags and OTHER_SPORT_RE.search(tags):
        return False  # the site itself filed it under another sport
    text = f"{title} {description[:600]}"
    if OTHER_SPORT_RE.search(text) and not re.search(r"\b(soccer|premier league|la liga|serie a|bundesliga|champions league)\b", text, re.I):
        return False
    return True if soccer_only else bool(SOCCER_RE.search(text))


def upgrade_image_url(url):
    """Ask well-known CDNs for a bigger version of a thumbnail (original is tried if this fails)."""
    new = url
    # BBC thumbnails: .../standard/240/... -> .../standard/976/...
    new = re.sub(r"(ichef\.bbci\.co\.uk/(?:ace/)?(?:standard|news|live)/)\d+/", r"\g<1>976/", new)
    # WordPress resized files: photo-150x150.jpg / photo-300x200.jpg -> photo.jpg
    new = re.sub(r"-\d{2,4}x\d{2,4}(\.(?:jpe?g|png|webp))(\?|$)", r"\1\2", new, flags=re.I)
    # Plain width/height query hints (not on signed CDN links)
    if "i.guim.co.uk" not in new and "s=" not in urlparse(new).query:
        new = re.sub(r"([?&])(w|width)=\d+", r"\g<1>\g<2>=1280", new)
    return new


def entry_images(entry):
    """Return candidate article image URLs, preferring larger RSS-provided images."""
    candidates = []
    seen = set()
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key, []) or []:
            url = item.get("url")
            if url and str(url).startswith(("https://", "http://")) and url not in seen:
                try:
                    width = int(item.get("width") or 0)
                    height = int(item.get("height") or 0)
                except (TypeError, ValueError):
                    width, height = 0, 0
                candidates.append((width * height, url))
                seen.add(url)
    for item in entry.get("links", []) or []:
        url = item.get("href", "")
        if item.get("rel") == "enclosure" and str(item.get("type", "")).startswith("image/") and url not in seen:
            candidates.append((0, url))
            seen.add(url)
    for key in ("summary", "description", "content"):
        val = entry.get(key, "")
        if isinstance(val, list):
            val = " ".join(str(x.get("value", "")) for x in val)
        for match in re.finditer(r'<img\b[^>]*?src=["\']([^"\']+)', str(val), re.I):
            url = html.unescape(match.group(1))
            if url.startswith(("https://", "http://")) and url not in seen:
                candidates.append((0, url))
                seen.add(url)
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in candidates]


def image_is_usable(url, min_w=MIN_IMAGE_WIDTH, min_h=MIN_IMAGE_HEIGHT):
    """Reject missing, inaccessible, too-small, or visibly soft images before publishing."""
    if not url or not str(url).startswith(("https://", "http://")):
        return False
    key = (url, min_w, min_h)
    if key in IMAGE_CHECK_CACHE:
        return IMAGE_CHECK_CACHE[key]
    usable = False
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=IMAGE_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                IMAGE_CHECK_CACHE[key] = False
                return False
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            IMAGE_CHECK_CACHE[key] = False
            return False
        with Image.open(BytesIO(data)) as original:
            original.verify()
        with Image.open(BytesIO(data)) as original:
            if original.width < min_w or original.height < min_h:
                IMAGE_CHECK_CACHE[key] = False
                return False
            # Landscape only, so cards never show awkward tall or square crops.
            if original.width / original.height < 1.3:
                IMAGE_CHECK_CACHE[key] = False
                return False
            gray = original.convert("L")
            gray.thumbnail((320, 180))
            # Edge energy: low variance after an edge filter generally indicates blur.
            edges = gray.filter(ImageFilter.FIND_EDGES)
            sharpness = ImageStat.Stat(edges).var[0]
            usable = sharpness >= MIN_SHARPNESS
    except Exception:
        usable = False
    IMAGE_CHECK_CACHE[key] = usable
    return usable


def best_image(entry, min_w, min_h):
    """First candidate (trying an upgraded URL before the original) that passes the quality checks."""
    for candidate in entry_images(entry):
        upgraded = upgrade_image_url(candidate)
        for url in ([upgraded, candidate] if upgraded != candidate else [candidate]):
            if image_is_usable(url, min_w, min_h):
                return url
    return ""


def entry_description(entry):
    """Prefer the richest available RSS body/summary, then fall back safely."""
    candidates = []
    for key in ("content", "summary", "description"):
        value = entry.get(key, "")
        if isinstance(value, list):
            value = " ".join(str(x.get("value", "")) for x in value if isinstance(x, dict))
        if value:
            plain = clean(html.unescape(re.sub(r"<[^>]+>", " ", str(value))))
            if plain:
                candidates.append(plain)
    # Keep the longest available text (up to the output limit).
    value = max(candidates, key=len) if candidates else ""
    return value[:3000]


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                # feedparser returns UTC struct_time; calendar.timegm avoids local-timezone skew.
                return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc)
            except Exception:
                pass
    for key in ("published", "updated", "pubDate"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def make_xml(items, title):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>',
             f'<title>{text_html(title)}</title>',
             '<link>https://example.com/</link>',
             '<description>Aggregated headlines linking to original publishers</description>']
    for x in items[:5000]:
        parts += ['<item>',
                  f'<title>{text_html(x["title"])}</title>',
                  f'<link>{html.escape(x["link"], quote=False)}</link>',
                  f'<guid isPermaLink="false">{hashlib.sha256(x["link"].encode()).hexdigest()}</guid>',
                  f'<source>{text_html(x["source"])}</source>',
                  f'<category>{text_html(x["category"])}</category>',
                  f'<pubDate>{format_datetime(x["date"])}</pubDate>',
                  f'<description>{text_html(x["description"])}</description>']
        if x["image"]:
            img = html.escape(x["image"], quote=True)
            mime = mimetypes.guess_type(urlparse(x["image"]).path)[0] or "image/jpeg"
            parts += [f'<enclosure url="{img}" type="{mime}"/>',
                      f'<media:content url="{img}" medium="image"/>']
        parts += ['</item>']
    parts += ['</channel></rss>']
    return '\n'.join(parts) + '\n'


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    grouped = {c: [] for c in CATEGORIES}
    seen_urls, seen_titles = set(), set()
    enabled = [s for s in config.get("sources", []) if s.get("enabled", True) and s.get("url")]
    ok_sources, failed_sources, total = 0, 0, 0
    skipped_not_soccer = skipped_thin = skipped_image = 0

    for source in enabled:
        name, url = clean(source.get("name")) or "Source", source["url"].strip()
        category = clean(source.get("category", "other")).lower()
        # "top" is generated automatically; sources can't be assigned to it directly.
        if category not in CATEGORIES:
            category = "other"
        elif category == "top":
            category = "world"
        is_sports = category == "sports"
        soccer_only = bool(source.get("soccer_only"))
        try:
            parsed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT}, resolve_relative_uris=True)
            if parsed.bozo and not parsed.entries:
                raise ValueError(str(getattr(parsed, "bozo_exception", "invalid feed")))
            if not parsed.entries:
                raise ValueError("feed returned no entries")
            ok_sources += 1
            for entry in parsed.entries[:MAX_PER_SOURCE]:
                link = canonical_url(entry.get("link", ""))
                title = clean(entry.get("title", ""))
                if not link or not title:
                    continue
                title_key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
                # Check duplicates first so we don't waste network calls on image checks.
                if link in seen_urls or (title_key and title_key in seen_titles):
                    continue
                description = entry_description(entry)

                if is_sports:
                    # Sports: full headline and a real body (soccer only if SPORTS_SOCCER_ONLY).
                    if SPORTS_SOCCER_ONLY and not is_soccer(title, description, soccer_only, entry_tags(entry), link):
                        skipped_not_soccer += 1
                        continue
                    if len(title) < SPORTS_MIN_TITLE_CHARS or len(description) < SPORTS_MIN_BODY_CHARS:
                        skipped_thin += 1
                        continue
                    min_w, min_h = SPORTS_MIN_IMAGE_WIDTH, SPORTS_MIN_IMAGE_HEIGHT
                else:
                    # For sources flagged "require_body", skip stories that have a headline but no summary text.
                    if source.get("require_body") and len(description) < MIN_BODY_CHARS:
                        continue
                    min_w, min_h = MIN_IMAGE_WIDTH, MIN_IMAGE_HEIGHT

                # Try each image candidate; skip the article if none passes quality checks.
                image = best_image(entry, min_w, min_h)
                if not image:
                    if is_sports:
                        skipped_image += 1
                    continue
                seen_urls.add(link)
                seen_titles.add(title_key)
                grouped[category].append({
                    "title": title, "link": link, "source": name,
                    "date": entry_date(entry), "description": description,
                    "image": image, "category": category,
                })
                total += 1
        except Exception as exc:
            failed_sources += 1
            print(f"WARN: {name}: {exc}")

    if not ok_sources:
        raise SystemExit("No configured RSS sources could be read; refusing to publish empty feeds.")

    # Top includes all categories (already globally deduplicated).
    grouped["top"] = [item for c, items in grouped.items() if c != "top" for item in items]

    for category, items in grouped.items():
        items.sort(key=lambda x: x["date"], reverse=True)
        (OUT / f"{category}.xml").write_text(make_xml(items, f"{category.title()} News"), encoding="utf-8")

    # JSON preview
    preview = {
        category: [
            {
                "title": item["title"],
                "link": item["link"],
                "source": item["source"],
                "date": item["date"].isoformat().replace("+00:00", "Z"),
                "description": item["description"],
                "image": item["image"],
                "category": item["category"],
            }
            for item in grouped[category][:PREVIEW_LIMIT]
        ]
        for category in PREVIEW_CATEGORIES
    }
    (ROOT / "news-preview.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Collection complete: {ok_sources}/{len(enabled)} sources OK; {failed_sources} failed; {total} unique articles.")
    print(f"Sports: {len(grouped['sports'])} stories kept; skipped {skipped_not_soccer} not-soccer, "
          f"{skipped_thin} thin text, {skipped_image} without an HD image.")


if __name__ == "__main__":
    main()
