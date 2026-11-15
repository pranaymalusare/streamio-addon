"""
Stremio catalog add-on: recently released Hindi and Marathi movies and series
that are streaming in India on Netflix, Prime Video, ZEE5, SonyLIV and JioHotstar
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

# Stremio type -> how TMDB names things for that type.
KINDS = {
    "movie": {"path": "movie", "date": "primary_release_date"},
    "series": {"path": "tv", "date": "first_air_date"},
}
MAX_SEASONS = 30  # safety cap when listing episodes

MANIFEST = {
    "id": "community.indian-ott-recent",
    "version": "1.1.0",
    "name": "Indian OTT - New Hindi & Marathi Movies & Series",
    "description": (
        "Recently released Hindi and Marathi movies and series streaming in India on "
        "Netflix, Prime Video, ZEE5, SonyLIV and JioHotstar. "
        "Data from TMDB; streaming availability by JustWatch."
    ),
    "resources": [
        "catalog",
        {"name": "meta", "types": ["movie", "series"], "idPrefixes": ["tmdb:"]},
    ],
    "types": ["movie", "series"],
    "idPrefixes": ["tt", "tmdb:"],
    "catalogs": [
        {
            "type": type_,
            "id": f"{code}-recent",
            "name": f"New {name} {label} on OTT",
            "extra": [
                {"name": "genre", "options": list(PLATFORMS), "isRequired": False},
                {"name": "skip", "isRequired": False},
            ],
        }
        for type_, label in (("movie", "Movies"), ("series", "Series"))
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


def to_meta(detail: dict, type_: str) -> dict:
    """Build a Stremio meta object from a TMDB movie / TV detail record."""
    imdb_id = (detail.get("external_ids") or {}).get("imdb_id") or detail.get("imdb_id")
    on = platforms_of(detail)
    overview = detail.get("overview") or ""
    description = (f"Streaming on: {', '.join(on)}\n\n" if on else "") + overview
    # Movies use title / release_date; series use name / first_air_date.
    release = detail.get("release_date") or detail.get("first_air_date") or ""
    runtime = detail.get("runtime") or next(iter(detail.get("episode_run_time") or []), None)
    meta = {
        "id": imdb_id or f"tmdb:{detail['id']}",
        "type": type_,
        "name": (detail.get("title") or detail.get("name")
                 or detail.get("original_title") or detail.get("original_name")),
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
    if runtime:
        meta["runtime"] = f"{runtime} min"
    return meta


async def title_detail(type_: str, tmdb_id: int) -> dict:
    return await tmdb_get(f"/{KINDS[type_]['path']}/{tmdb_id}", DETAIL_TTL,
                          append_to_response="external_ids,watch/providers")


async def episode_list(detail: dict) -> list[dict]:
    """Stremio 'videos' (episodes) for a series that has no IMDb id."""
    numbers = [s["season_number"] for s in detail.get("seasons", [])
               if s.get("season_number")][:MAX_SEASONS]          # skips specials (0)
    seasons = await asyncio.gather(
        *(tmdb_get(f"/tv/{detail['id']}/season/{n}", DETAIL_TTL) for n in numbers),
        return_exceptions=True,
    )
    videos = []
    for season in seasons:
        if not isinstance(season, dict):
            continue
        for ep in season.get("episodes", []):
            s_no, e_no = ep["season_number"], ep["episode_number"]
            video = {
                "id": f"tmdb:{detail['id']}:{s_no}:{e_no}",
                "title": ep.get("name") or f"Episode {e_no}",
                "season": s_no,
                "episode": e_no,
                "overview": ep.get("overview") or "",
            }
            if ep.get("air_date"):
                video["released"] = f"{ep['air_date']}T00:00:00.000Z"
            if ep.get("still_path"):
                video["thumbnail"] = f"{IMG}/w300{ep['still_path']}"
            videos.append(video)
    return videos


async def build_catalog(type_: str, lang: str, platform: str | None, skip: int) -> list[dict]:
    kind = KINDS[type_]
    provider_ids = PLATFORMS[platform] if platform else list(ID_TO_PLATFORM)
    today = date.today()
    page = await tmdb_get(
        f"/discover/{kind['path']}", CATALOG_TTL,
        with_original_language=lang,
        watch_region=REGION,
        with_watch_providers="|".join(map(str, provider_ids)),   # | means OR
        with_watch_monetization_types="flatrate|free|ads",
        sort_by=f"{kind['date']}.desc",
        **{f"{kind['date']}.lte": today.isoformat(),
           f"{kind['date']}.gte": (today - timedelta(days=DAYS_BACK)).isoformat()},
        include_adult="false",
        page=skip // PAGE_SIZE + 1,
    )
    details = await asyncio.gather(
        *(title_detail(type_, m["id"]) for m in page.get("results", [])),
        return_exceptions=True,
    )
    return [to_meta(d, type_) for d in details if isinstance(d, dict)]


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
    if type_ not in KINDS or lang not in LANGUAGES:
        return {"metas": []}
    args = {k: v[0] for k, v in parse_qs(extra).items()}
    platform = args.get("genre")
    if platform and platform not in PLATFORMS:
        return {"metas": []}
    skip = int(args.get("skip", 0) or 0)
    metas = await build_catalog(type_, lang, platform, skip)
    return {"metas": metas, "cacheMaxAge": CATALOG_TTL}


@app.get("/meta/{type_}/{meta_id}.json")
async def meta(type_: str, meta_id: str):
    """Only used for titles without an IMDb id (ids like tmdb:12345)."""
    if type_ not in KINDS or not meta_id.startswith("tmdb:"):
        return {"meta": None}
    try:
        detail = await title_detail(type_, int(meta_id.split(":")[1]))
    except ValueError:
        return {"meta": None}
    result = to_meta(detail, type_)
    if type_ == "series":
        result["videos"] = await episode_list(detail)
    return {"meta": result, "cacheMaxAge": DETAIL_TTL}
