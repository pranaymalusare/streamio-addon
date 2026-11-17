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
- In these four, the genre dropdown filters by platform.
- Each description starts with "Streaming on: …".
- A fifth catalog in Discover → Movies: **Must-Watch Indian Movies (Other
  Languages)**. Movies only, no series.
  - Languages: Tamil, Telugu, Malayalam, Kannada, Bengali, Punjabi, Gujarati,
    Assamese, Odia and other Indian languages. Hindi and Marathi are excluded.
  - Rating 7.5+ (TMDB score, with at least 50 votes), best first.
  - Released in the last 10 years. The window moves forward every 1 January.
  - Default view: Comedy, Thriller, Mystery and Crime. The genre dropdown
    switches to one genre or to "All genres".

- A sixth catalog: **What is India Watching**. Movies and series together,
  any language. It takes the 5 most popular titles from Netflix, then Prime
  Video, SonyLIV, ZEE5 and JioHotstar, then the next 5 from each, up to 50.
  Popularity is TMDB's score for titles available on each platform in India;
  it is not the platforms' own Top 10 charts.

## When the data updates

- Catalog pages are cached for 1 hour (`CATALOG_TTL`); title details for 24.
- TMDB refreshes streaming availability from JustWatch about once a day.

## Settings (environment variables)

| Variable      | Default | Meaning                               |
|---------------|---------|---------------------------------------|
| `DAYS_BACK`   | 365     | How far back "recent" goes            |
| `CATALOG_TTL` | 3600    | Seconds to cache catalog pages        |
| `MIN_RATING`  | 7.5     | Must-watch: minimum TMDB rating       |
| `MIN_VOTES`   | 50      | Must-watch: minimum number of votes   |
| `YEARS_BACK`  | 10      | Must-watch: how many years back       |

## Notes

- Stremio on TV/phone or the web app needs an HTTPS URL. Deploy the add-on
  to a host such as Render or Fly.io for that; `127.0.0.1` works for the
  desktop app only.
- Sorting is by release date, not by the date a title landed on a platform
  (TMDB does not expose that date).
- Platform IDs live in `PLATFORMS` in `addon.py`. Check them against
  `/watch/providers/movie?watch_region=IN` on TMDB.
- Data from TMDB; streaming availability by JustWatch.
