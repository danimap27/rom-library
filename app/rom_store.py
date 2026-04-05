"""
ROM Store — browse, search and download ROMs from Archive.org.
Includes in-memory cache, game name search, and pack generator.
"""
import re
import time
import random
import asyncio
import httpx
from pathlib import Path

# ── Collections ────────────────────────────────────────────────────────────────

ARCHIVE_COLLECTIONS: dict[str, list[dict]] = {
    "NintendoDS": [
        {"id": "nds-roms-free",                        "name": "NDS ROMs Free"},
        {"id": "nintendo-ds-roms",                     "name": "Nintendo DS ROMs"},
        {"id": "nds-rom-hack-collection",              "name": "NDS ROM Hacks"},
        {"id": "democollectionfornintendods",           "name": "NDS Demos Collection"},
    ],
    "GBA": [
        {"id": "gba-roms",                             "name": "GBA ROMs"},
        {"id": "gba-games-pack",                       "name": "GBA Games Pack"},
        {"id": "gba-rom-hacks",                        "name": "GBA ROM Hacks"},
    ],
    "GB": [
        {"id": "nintendo-game-boy-library-roms",       "name": "Game Boy Library"},
    ],
    "GBC": [
        {"id": "nintendo-game-boy-color-library-roms", "name": "Game Boy Color Library"},
    ],
    "SNES": [
        {"id": "snes-roms-collection",                 "name": "SNES ROMs"},
        {"id": "super-nintendo-usa",                   "name": "SNES USA Set"},
        {"id": "super-famicom-japan",                  "name": "Super Famicom Japan"},
    ],
    "NES": [
        {"id": "nes-roms",                             "name": "NES ROMs"},
        {"id": "nintendo-nes-library-roms",            "name": "NES Library"},
    ],
    "N64": [
        {"id": "n64-roms",                             "name": "N64 ROMs"},
        {"id": "nintendo-64-library-roms",             "name": "N64 Library"},
    ],
    "PS1": [
        {"id": "ps1-roms-collection",                  "name": "PS1 ROMs"},
        {"id": "redump-sony-playstation",              "name": "PS1 Redump"},
        {"id": "psx-roms",                             "name": "PSX ROMs"},
    ],
    "PS2": [
        {"id": "ps2-eu",                               "name": "PS2 Europe"},
        {"id": "ps2-roms-free",                        "name": "PS2 ROMs Free"},
        {"id": "ps2-usa",                              "name": "PS2 USA"},
    ],
    "PSP": [
        {"id": "psp-roms-free",                        "name": "PSP ROMs Free"},
        {"id": "psp-isos",                             "name": "PSP ISOs"},
        {"id": "psp-cso-collection",                   "name": "PSP CSO Pack"},
    ],
    "MegaDrive": [
        {"id": "sega-genesis-roms",                    "name": "Sega Genesis ROMs"},
        {"id": "sega-megadrive",                       "name": "Mega Drive"},
    ],
    "GameGear": [
        {"id": "sega-game-gear-library-roms",          "name": "Game Gear Library"},
    ],
    "GameCube": [
        {"id": "gamecube-isos",                        "name": "GameCube ISOs"},
        {"id": "gamecube-europe",                      "name": "GameCube Europe"},
    ],
    "Wii": [
        {"id": "wii-iso",                              "name": "Wii ISOs"},
        {"id": "wii-europe",                           "name": "Wii Europe"},
    ],
    "Nintendo3DS": [
        {"id": "nintendo-3ds-complete-collection",     "name": "3DS Collection"},
    ],
}

from .scanner import CONSOLE_EXTENSIONS

# ── Cache ──────────────────────────────────────────────────────────────────────

_file_cache: dict[str, tuple[list, float]] = {}  # identifier → (files, ts)
CACHE_TTL = 3600  # 1 hour


def _cache_get(key: str) -> list | None:
    if key in _file_cache:
        files, ts = _file_cache[key]
        if time.time() - ts < CACHE_TTL:
            return files
    return None


def _cache_set(key: str, files: list):
    _file_cache[key] = (files, time.time())


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_name(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name)
    name = name.replace("_", " ").replace(".", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name.strip()


# ── Fetchers ───────────────────────────────────────────────────────────────────

async def get_collection_files(identifier: str, console: str) -> list[dict]:
    """Fetch and cache file list from one Archive.org item."""
    cache_key = f"{identifier}:{console}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    extensions = set(CONSOLE_EXTENSIONS.get(console, []))
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(
                f"https://archive.org/metadata/{identifier}/files",
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return [{"error": str(e)}]

    files = []
    for f in data.get("result", []):
        raw_name = f.get("name", "")
        # Get just the filename if it's inside a subfolder
        basename = raw_name.split("/")[-1]
        if not any(basename.lower().endswith(ext) for ext in extensions):
            continue
        size = int(f.get("size", 0))
        # URL must use the original path (may include subfolder)
        url = f"https://archive.org/download/{identifier}/{raw_name}"
        files.append({
            "filename": basename,
            "title": _clean_name(basename) or basename,
            "size": size,
            "url": url,
            "collection": identifier,
        })

    files.sort(key=lambda x: x["title"].lower())
    if files:  # only cache successful results
        _cache_set(cache_key, files)
    return files


async def get_all_console_files(console: str) -> list[dict]:
    """Fetch and merge files from ALL collections for a console, in parallel."""
    collections = ARCHIVE_COLLECTIONS.get(console, [])
    if not collections:
        return []
    tasks = [get_collection_files(col["id"], console) for col in collections]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_titles: set[str] = set()
    merged = []
    for result in results:
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        for f in result:
            if f.get("error"):
                continue
            key = f["title"].lower()
            if key not in seen_titles:
                seen_titles.add(key)
                merged.append(f)
    return merged


# ── Search by game name ────────────────────────────────────────────────────────

async def search_by_name(query: str, console: str) -> list[dict]:
    """
    Search for a game by name across all collections for the given console.
    Returns files whose title contains the query (case-insensitive).
    Falls back to Archive.org full-text search if local results are few.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    all_files = await get_all_console_files(console)

    # Score-based match: exact title match → prefix match → substring match
    scored = []
    for f in all_files:
        title = f["title"].lower()
        if title == query_lower:
            scored.append((0, f))
        elif title.startswith(query_lower):
            scored.append((1, f))
        elif query_lower in title:
            scored.append((2, f))

    scored.sort(key=lambda x: (x[0], x[1]["title"].lower()))
    local_results = [f for _, f in scored]

    # If we got local results, return them (possibly supplemented by Archive.org search)
    if len(local_results) >= 3:
        return local_results[:30]

    # Fall back: search Archive.org items and resolve file URLs
    archive_results = await _search_archive_resolve(query, console)
    # Deduplicate with local
    local_titles = {f["title"].lower() for f in local_results}
    for f in archive_results:
        if f["title"].lower() not in local_titles:
            local_results.append(f)
    return local_results[:30]


async def _search_archive_resolve(query: str, console: str) -> list[dict]:
    """
    Search Archive.org for items matching the query, then resolve direct
    file download URLs from the first few results.
    """
    extensions = CONSOLE_EXTENSIONS.get(console, [])
    if not extensions:
        return []

    search_q = f'title:"{query}" AND mediatype:(software OR data)'
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": search_q,
                    "output": "json",
                    "fl[]": ["identifier", "title"],
                    "rows": 6,
                    "sort[]": "downloads desc",
                },
            )
            docs = r.json().get("response", {}).get("docs", [])
    except Exception:
        return []

    # Resolve files from top results (limit to 3 items to stay fast)
    tasks = [get_collection_files(d["identifier"], console) for d in docs[:3]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    files = []
    q_lower = query.lower()
    for result in results:
        if not isinstance(result, list):
            continue
        for f in result:
            if not f.get("error") and q_lower in f["title"].lower():
                files.append(f)
    return files


# ── Pack generator ─────────────────────────────────────────────────────────────

def build_pack(
    files: list[dict],
    max_bytes: int,
    strategy: str = "random",
    min_size_mb: int = 1,
) -> tuple[list[dict], int]:
    """
    Select games to fill a target size.
    strategy: 'random' | 'largest' | 'smallest'
    Returns (selected_files, total_bytes).
    """
    # Filter out empty/metadata files
    min_bytes = min_size_mb * 1024 * 1024
    valid = [f for f in files if f.get("size", 0) >= min_bytes and f["size"] <= max_bytes]

    if strategy == "random":
        random.shuffle(valid)
    elif strategy == "largest":
        valid.sort(key=lambda x: x["size"], reverse=True)
    elif strategy == "smallest":
        valid.sort(key=lambda x: x["size"])

    selected = []
    total = 0
    for f in valid:
        if total + f["size"] <= max_bytes:
            selected.append(f)
            total += f["size"]
    return selected, total


async def search_archive_global(query: str, console: str) -> list[dict]:
    """Quick Archive.org item search (for 'see more results' links)."""
    search_q = f'title:"{query}" AND mediatype:(software OR data)'
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": search_q,
                    "output": "json",
                    "fl[]": ["identifier", "title", "description", "downloads"],
                    "rows": 10,
                    "sort[]": "downloads desc",
                },
            )
            docs = r.json().get("response", {}).get("docs", [])
        return [
            {
                "identifier": d.get("identifier"),
                "title": d.get("title", d.get("identifier")),
                "description": (d.get("description") or "")[:100],
                "downloads": d.get("downloads", 0),
            }
            for d in docs
        ]
    except Exception:
        return []
