#!/usr/bin/env python3
"""
Find Creative Commons licensed money/business/investing podcasts on YouTube.

Every candidate's license is verified against the video's OWN record
(videos.list -> status.license), never inferred from the search filter alone.

Usage:
    export YOUTUBE_API_KEY=...
    python3 scripts/yt_cc_business_search.py --out out/

Requires network access to www.googleapis.com.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://www.googleapis.com/youtube/v3"

QUERIES = [
    "podcast money business",
    "business podcast",
    "investing podcast",
    "personal finance podcast",
    "entrepreneurship podcast",
    "startup podcast",
    "stock market podcast",
    "economics podcast",
    "financial freedom podcast",
    "real estate investing podcast",
    "بودكاست مال وأعمال",
    "بودكاست استثمار",
    "بودكاست ريادة أعمال",
    "بودكاست اقتصاد",
    "بودكاست تمويل شخصي",
]

# Terms that mark a video as genuinely on-topic. The CC filter returns plenty of
# unrelated material, so topic relevance is scored separately from the license.
TOPIC_TERMS = [
    "money", "business", "invest", "investing", "investor", "finance",
    "financial", "stock", "market", "economy", "economic", "entrepreneur",
    "startup", "wealth", "trading", "trader", "crypto", "revenue", "profit",
    "budget", "saving", "retirement", "portfolio", "real estate", "capital",
    "funding", "venture", "acquisition", "cash flow", "income",
    "مال", "أعمال", "اقتصاد", "استثمار", "تمويل", "ريادة", "تداول",
    "أسهم", "ثروة", "ميزانية", "ادخار", "شركات", "مشروع",
]

PODCAST_TERMS = ["podcast", "episode", "ep.", "interview", "بودكاست", "حلقة", "مقابلة"]


def api_get(endpoint, params, key):
    params = dict(params)
    params["key"] = key
    url = f"{API}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (403, 429) and "quota" not in body.lower() and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            sys.stderr.write(f"HTTP {e.code} on {endpoint}: {body[:400]}\n")
            raise
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            sys.stderr.write(f"network error on {endpoint}: {e}\n")
            raise
    return {}


def search_cc_videos(query, key, pages=2):
    """Step 1: search with the Creative Commons filter applied server-side."""
    ids, token = [], None
    for _ in range(pages):
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoLicense": "creativeCommon",   # == Filters -> Creative Commons
            "order": "viewCount",
            "maxResults": 50,
        }
        if token:
            params["pageToken"] = token
        data = api_get("search", params, key)
        ids += [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def verify_videos(video_ids, key):
    """Step 2: confirm the license on each video's own record, not the filter."""
    out = {}
    for batch in chunked(sorted(set(video_ids)), 50):
        data = api_get("videos", {
            "part": "snippet,status,statistics",
            "id": ",".join(batch),
        }, key)
        for item in data.get("items", []):
            if item.get("status", {}).get("license") != "creativeCommon":
                continue  # filter said CC, the video record disagrees -> drop it
            out[item["id"]] = item
    return out


def topic_score(item):
    sn = item["snippet"]
    blob = " ".join([
        sn.get("title", ""), sn.get("description", "")[:1500],
        " ".join(sn.get("tags", []) or []), sn.get("channelTitle", ""),
    ]).lower()
    hits = sorted({t for t in TOPIC_TERMS if t in blob})
    is_pod = any(t in blob for t in PODCAST_TERMS)
    return len(hits), hits[:8], is_pod


def channel_activity(channel_ids, key):
    """Step 4b: channel size + how recently it actually published."""
    info = {}
    for batch in chunked(sorted(set(channel_ids)), 50):
        data = api_get("channels", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
        }, key)
        for ch in data.get("items", []):
            uploads = ch["contentDetails"]["relatedPlaylists"].get("uploads")
            last = None
            if uploads:
                pl = api_get("playlistItems", {
                    "part": "snippet", "playlistId": uploads, "maxResults": 5,
                }, key)
                dates = [i["snippet"]["publishedAt"] for i in pl.get("items", [])]
                last = max(dates) if dates else None
            info[ch["id"]] = {
                "title": ch["snippet"]["title"],
                "subs": int(ch["statistics"].get("subscriberCount", 0) or 0),
                "videos": int(ch["statistics"].get("videoCount", 0) or 0),
                "last_upload": last,
            }
    return info


def days_since(ts):
    if not ts:
        return None
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - d).days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--pages", type=int, default=2, help="search pages per query")
    ap.add_argument("--min-topic-hits", type=int, default=2)
    args = ap.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("YOUTUBE_API_KEY is not set. Get one at console.cloud.google.com "
                 "(enable 'YouTube Data API v3').")

    all_ids = []
    for q in QUERIES:
        try:
            found = search_cc_videos(q, key, args.pages)
        except Exception as e:
            sys.stderr.write(f"query failed {q!r}: {e}\n")
            continue
        print(f"[search] {q!r}: {len(found)} CC-filtered results", file=sys.stderr)
        all_ids += found

    print(f"[search] {len(set(all_ids))} unique videos to verify", file=sys.stderr)
    verified = verify_videos(all_ids, key)
    print(f"[verify] {len(verified)} confirmed status.license == creativeCommon",
          file=sys.stderr)

    rows = []
    for vid, item in verified.items():
        hits, sample, is_pod = topic_score(item)
        if hits < args.min_topic_hits:
            continue
        rows.append({
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "channel_id": item["snippet"]["channelId"],
            "published": item["snippet"]["publishedAt"],
            "views": int(item["statistics"].get("viewCount", 0) or 0),
            "license_verified": "creativeCommon (videos.list status.license)",
            "topic_hits": hits,
            "topic_terms": sample,
            "podcast_shaped": is_pod,
        })

    chans = channel_activity([r["channel_id"] for r in rows], key)
    for r in rows:
        c = chans.get(r["channel_id"], {})
        r["subs"] = c.get("subs", 0)
        r["channel_videos"] = c.get("videos", 0)
        r["last_upload"] = c.get("last_upload")
        r["days_since_upload"] = days_since(c.get("last_upload"))

    # Step 4: rank by (a) reach and (b) how alive the channel is.
    def rank(r):
        reach = (r["views"] ** 0.5) + (r["subs"] ** 0.5) * 2
        d = r["days_since_upload"]
        active = 1.0 if d is None else (1.5 if d <= 30 else 1.2 if d <= 90
                                        else 1.0 if d <= 365 else 0.4)
        return reach * active * (1.2 if r["podcast_shaped"] else 1.0)

    rows.sort(key=rank, reverse=True)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    md = ["# Creative Commons money/business podcast candidates", "",
          f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · "
          f"{len(rows)} verified candidates", "",
          "| # | Channel | Title | Link | Views | Subs | Last upload | License |",
          "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        d = r["days_since_upload"]
        age = "unknown" if d is None else f"{d}d ago"
        md.append(f"| {i} | {r['channel']} | {r['title'][:60]} | {r['url']} | "
                  f"{r['views']:,} | {r['subs']:,} | {age} | CC (verified) |")
    with open(os.path.join(args.out, "candidates.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(f"[done] {len(rows)} candidates -> {args.out}/candidates.md", file=sys.stderr)


if __name__ == "__main__":
    main()
