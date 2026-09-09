# Creative Commons money/business podcast sourcing

Finds YouTube videos that are (a) genuinely about money/business/investing and
(b) actually licensed under Creative Commons, then ranks them by reach and by
how active the channel still is.

## Why a script and not the browser

youtube.com is blocked by this execution environment's network policy — both
`curl` and a real Chromium page load fail with `ERR_TUNNEL_CONNECTION_FAILED`
(egress proxy `connect_rejected`). `www.googleapis.com` *is* reachable, so the
YouTube Data API is the working path from here. Running the browser flow
instead requires allowing `youtube.com` in the environment's network policy.

## Running it

```
export YOUTUBE_API_KEY=...        # console.cloud.google.com -> enable "YouTube Data API v3"
python3 scripts/yt_cc_business_search.py --out out/
```

Writes `out/candidates.md` (ranked table) and `out/candidates.json`.

## How the license is verified

The search filter alone is not trusted. Two passes:

1. `search.list` with `videoLicense=creativeCommon` — the API equivalent of
   **Filters → Creative Commons**. This only *proposes* candidates.
2. `videos.list?part=status` on every proposed id — a candidate is kept only if
   its own record reports `status.license == "creativeCommon"`. Anything the
   filter returned but the video record does not confirm is dropped.

This is the same fact the "This video is licensed under Creative Commons" line
in the description renders from, read from the video itself rather than from the
result list.

## Topic relevance

The CC filter returns a lot of off-topic material, so relevance is scored
independently from the license: a candidate needs at least two distinct
money/business terms (English or Arabic) across its title, description, tags and
channel name. Tune with `--min-topic-hits`.

## Ranking

`sqrt(views) + 2*sqrt(subscribers)`, multiplied by an activity factor
(uploaded within 30d / 90d / 1y / dormant) and a small bonus for
podcast-shaped titles. Dormant channels are heavily discounted.
