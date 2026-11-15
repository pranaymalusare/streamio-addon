"""
Stremio catalog add-on: recently released Hindi and Marathi movies that are
streaming in India on Netflix, Prime Video, ZEE5, SonyLIV and JioHotstar
(JioCinema merged into JioHotstar in 2025).

Data source: TMDB "discover" API with India watch-provider filters
(provider availability on TMDB is supplied by JustWatch).

Run:
    export TMDB_API_KEY=xxxxxxxx          # v3 key, or
    export TMDB_BEARER_TOKEN=eyJ...       # v4 read-access token
    uvicorn addon:app --host 0.0.0.0 --port 7000

Install in Stremio:  http://127.0.0.1:7000/manifest.json
"""

import asyncio
import os
import time
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
TMDB = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
API_KEY = os.getenv("TMDB_API_KEY", "")
BEARER = os.getenv("TMDB_BEARER_TOKEN", "")
REGION = "IN"
DAYS_BACK = int(os.getenv("DAYS_BACK", "365"))      # how far back "recent" goes
PAGE_SIZE = 20                                      # TMDB page size
CATALOG_TTL = int(os.getenv("CATALOG_TTL", "3600"))  # 1 hour
DETAIL_TTL = 24 * 3600

# Platform name -> TMDB watch-provider IDs for region IN.
# Several IDs per platform cover ad tiers and re-brands.
PLATFORMS = {
    "Netflix": [8, 1796],            # Netflix, Netflix Standard with Ads
    "Prime Video": [119, 2100],      # Amazon Prime Video (+ with Ads)
    "ZEE5": [232],
    "SonyLIV": [237],
    "JioHotstar": [2336, 220, 122],  # JioHotstar, JioCinema, Hotstar (legacy)
}
ID_TO_PLATFORM = {pid: name for name, ids in PLATFORMS.items() for pid in ids}

LANGUAGES = {"hi": "Hindi", "mr": "Marathi"}

MANIFEST = {
    "id": "community.indian-ott-recent",
    "version": "1.0.0",
    "name": "Indian OTT - New Hindi & Marathi Movies",
    "description": (
        "Recently released Hindi and Marathi movies streaming in India on "
        "Netflix, Prime Video, ZEE5, SonyLIV and JioHotstar. "
        "Data from TMDB; streaming availability by JustWatch."
    ),
    "resources": [
        "catalog",
        {"name": "meta", "types": ["movie"], "idPrefixes": ["tmdb:"]},
    ],
    "types": ["movie"],
    "idPrefixes": ["tt", "tmdb:"],
    "catalogs": [
        {
            "type": "movie",
            "id": f"{code}-recent",
            "name": f"New {name} Movies on OTT",
            "extra": [
                {"name": "genre", "options": list(PLATFORMS), "isRequired": False},
                {"name": "skip", "isRequired": False},
            ],
        }
        for code, name in LANGUAGES.items()
    ],
    "behaviorHints": {"configurable": False},
}

# --------------------------------------------------------------------------
# App, HTTP client, tiny TTL cache
# --------------------------------------------------------------------------
app = FastAPI(title=MANIFEST["name"])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                   allow_headers=["*"])

_client: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, object]] = {}
_sem = asyncio.Semaphore(10)  # be polite to TMDB


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        headers = {"Authorization": f"Bearer {BEARER}"} if BEARER else {}
        _client = httpx.AsyncClient(base_url=TMDB, headers=headers, timeout=20)
    return _client


async def tmdb_get(path: str, ttl: int, **params):
    """GET a TMDB endpoint with caching."""
    if not (API_KEY or BEARER):
        raise HTTPException(500, "Set TMDB_API_KEY or TMDB_BEARER_TOKEN")
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    if API_KEY:
        params["api_key"] = API_KEY
    async with _sem:
        r = await client().get(path, params=params)
    if r.status_code != 200:
        raise HTTPException(502, f"TMDB error {r.status_code}: {r.text[:200]}")
    data = r.json()
    _cache[key] = (time.time() + ttl, data)
    return data


# --------------------------------------------------------------------------
# TMDB -> Stremio conversion
# --------------------------------------------------------------------------
def platforms_of(detail: dict) -> list[str]:
    """Names of our tracked platforms that stream this movie in India."""
    region = detail.get("watch/providers", {}).get("results", {}).get(REGION, {})
    names = []
    for kind in ("flatrate", "free", "ads"):
        for p in region.get(kind, []):
            name = ID_TO_PLATFORM.get(p["provider_id"])
            if name and name not in names:
                names.append(name)
    return names


def to_meta(detail: dict) -> dict:
    """Build a Stremio meta object from a TMDB movie detail record."""
    imdb_id = (detail.get("external_ids") or {}).get("imdb_id") or detail.get("imdb_id")
    on = platforms_of(detail)
    overview = detail.get("overview") or ""
    description = (f"Streaming on: {', '.join(on)}\n\n" if on else "") + overview
    release = detail.get("release_date") or ""
    meta = {
        "id": imdb_id or f"tmdb:{detail['id']}",
        "type": "movie",
        "name": detail.get("title") or detail.get("original_title"),
        "description": description,
        "releaseInfo": release[:4],
        "genres": [g["name"] for g in detail.get("genres", [])],
        "language": detail.get("original_language"),
    }
    if release:
        meta["released"] = f"{release}T00:00:00.000Z"
    if detail.get("poster_path"):
        meta["poster"] = f"{IMG}/w500{detail['poster_path']}"
    if detail.get("backdrop_path"):
        meta["background"] = f"{IMG}/w1280{detail['backdrop_path']}"
    if detail.get("vote_average"):
        meta["imdbRating"] = f"{detail['vote_average']:.1f}"
    if detail.get("runtime"):
        meta["runtime"] = f"{detail['runtime']} min"
    return meta


async def movie_detail(tmdb_id: int) -> dict:
    return await tmdb_get(f"/movie/{tmdb_id}", DETAIL_TTL,
                          append_to_response="external_ids,watch/providers")


async def build_catalog(lang: str, platform: str | None, skip: int) -> list[dict]:
    provider_ids = PLATFORMS[platform] if platform else list(ID_TO_PLATFORM)
    today = date.today()
    page = await tmdb_get(
        "/discover/movie", CATALOG_TTL,
        with_original_language=lang,
        watch_region=REGION,
        with_watch_providers="|".join(map(str, provider_ids)),   # | means OR
        with_watch_monetization_types="flatrate|free|ads",
        sort_by="primary_release_date.desc",
        **{"primary_release_date.lte": today.isoformat(),
           "primary_release_date.gte": (today - timedelta(days=DAYS_BACK)).isoformat()},
        include_adult="false",
        page=skip // PAGE_SIZE + 1,
    )
    details = await asyncio.gather(
        *(movie_detail(m["id"]) for m in page.get("results", [])),
        return_exceptions=True,
    )
    return [to_meta(d) for d in details if isinstance(d, dict)]


# --------------------------------------------------------------------------
# Stremio routes
# --------------------------------------------------------------------------
@app.get("/")
@app.get("/manifest.json")
async def manifest():
    return MANIFEST


@app.get("/catalog/{type_}/{catalog_id}.json")
@app.get("/catalog/{type_}/{catalog_id}/{extra}.json")
async def catalog(type_: str, catalog_id: str, extra: str = ""):
    lang = catalog_id.removesuffix("-recent")
    if type_ != "movie" or lang not in LANGUAGES:
        return {"metas": []}
    args = {k: v[0] for k, v in parse_qs(extra).items()}
    platform = args.get("genre")
    if platform and platform not in PLATFORMS:
        return {"metas": []}
    skip = int(args.get("skip", 0) or 0)
    metas = await build_catalog(lang, platform, skip)
    return {"metas": metas, "cacheMaxAge": CATALOG_TTL}


@app.get("/meta/{type_}/{meta_id}.json")
async def meta(type_: str, meta_id: str):
    """Only used for movies without an IMDb id (ids like tmdb:12345)."""
    if type_ != "movie" or not meta_id.startswith("tmdb:"):
        return {"meta": None}
    try:
        detail = await movie_detail(int(meta_id.split(":", 1)[1]))
    except ValueError:
        return {"meta": None}
    return {"meta": to_meta(detail), "cacheMaxAge": DETAIL_TTL}
