# Indian OTT – New Hindi & Marathi Movies & Series (Stremio add-on)

A Stremio **catalog** add-on. It lists recently released Hindi and Marathi
movies streaming in India on Netflix, Prime Video, ZEE5, SonyLIV and
JioHotstar (JioCinema merged into JioHotstar in 2025).

## Run

1. Get a free TMDB key: themoviedb.org → Settings → API.
2. Install and start:

```bash
pip install -r requirements.txt
```

```bash
export TMDB_API_KEY=your_v3_key
```

```bash
uvicorn addon:app --host 0.0.0.0 --port 7000
```

3. In Stremio, paste `http://127.0.0.1:7000/manifest.json` into the add-on
   search box and click Install.

Use `TMDB_BEARER_TOKEN` instead of `TMDB_API_KEY` if you have the long
"API Read Access Token".

## What you get

- Four catalogs in Discover: **New Hindi/Marathi Movies on OTT** (Movies) and
  **New Hindi/Marathi Series on OTT** (Series).
- The genre dropdown filters by platform.
- Each description starts with "Streaming on: …".

## Settings (environment variables)

| Variable      | Default | Meaning                               |
|---------------|---------|---------------------------------------|
| `DAYS_BACK`   | 365     | How far back "recent" goes            |
| `CATALOG_TTL` | 3600    | Seconds to cache catalog pages        |

## Notes

- Stremio on TV/phone or the web app needs an HTTPS URL. Deploy the add-on
  to a host such as Render or Fly.io for that; `127.0.0.1` works for the
  desktop app only.
- Sorting is by release date, not by the date a title landed on a platform
  (TMDB does not expose that date).
- Platform IDs live in `PLATFORMS` in `addon.py`. Check them against
  `/watch/providers/movie?watch_region=IN` on TMDB.
- Data from TMDB; streaming availability by JustWatch.
