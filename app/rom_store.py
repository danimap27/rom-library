"""
ROM Store — browse and download ROMs from Archive.org collections.
Uses the Archive.org metadata API (no authentication needed).
"""
import re
import httpx
from pathlib import Path

# Curated Archive.org item identifiers, verified to contain ROM collections.
# Each entry: {"id": archive_identifier, "name": display_name, "lang": language hint}
ARCHIVE_COLLECTIONS: dict[str, list[dict]] = {
    "NintendoDS": [
        {"id": "nds-roms-free",                  "name": "NDS ROMs Free",           "lang": "multi"},
        {"id": "nintendo-ds-roms",               "name": "Nintendo DS ROMs",         "lang": "multi"},
        {"id": "nds-rom-hack-collection",        "name": "NDS ROM Hacks",            "lang": "multi"},
    ],
    "GBA": [
        {"id": "gba-roms",                       "name": "GBA ROMs",                 "lang": "multi"},
        {"id": "gba-games-pack",                 "name": "GBA Games Pack",           "lang": "multi"},
    ],
    "GB": [
        {"id": "nintendo-game-boy-library-roms", "name": "Game Boy Library",         "lang": "multi"},
    ],
    "GBC": [
        {"id": "nintendo-game-boy-color-library-roms", "name": "Game Boy Color Library", "lang": "multi"},
    ],
    "SNES": [
        {"id": "snes-roms-collection",           "name": "SNES ROMs Collection",     "lang": "multi"},
        {"id": "super-nintendo-usa",             "name": "SNES USA",                 "lang": "en"},
    ],
    "NES": [
        {"id": "nes-roms",                       "name": "NES ROMs",                 "lang": "multi"},
        {"id": "nintendo-nes-library-roms",      "name": "NES Library",              "lang": "multi"},
    ],
    "N64": [
        {"id": "n64-roms",                       "name": "N64 ROMs",                 "lang": "multi"},
        {"id": "nintendo-64-library-roms",       "name": "N64 Library",              "lang": "multi"},
    ],
    "PS1": [
        {"id": "ps1-roms-collection",            "name": "PS1 ROMs",                 "lang": "multi"},
        {"id": "redump-sony-playstation",        "name": "PS1 Redump",               "lang": "multi"},
    ],
    "PS2": [
        {"id": "ps2-eu",                         "name": "PS2 Europe",               "lang": "eu"},
        {"id": "ps2-roms-free",                  "name": "PS2 ROMs Free",            "lang": "multi"},
    ],
    "PSP": [
        {"id": "psp-roms-free",                  "name": "PSP ROMs Free",            "lang": "multi"},
        {"id": "psp-isos",                       "name": "PSP ISOs",                 "lang": "multi"},
    ],
    "MegaDrive": [
        {"id": "sega-genesis-roms",              "name": "Sega Genesis ROMs",        "lang": "multi"},
        {"id": "sega-megadrive",                 "name": "Sega Mega Drive",          "lang": "multi"},
    ],
    "GameGear": [
        {"id": "sega-game-gear-library-roms",   "name": "Game Gear Library",        "lang": "multi"},
    ],
    "GameCube": [
        {"id": "gamecube-isos",                  "name": "GameCube ISOs",            "lang": "multi"},
    ],
    "Wii": [
        {"id": "wii-iso",                        "name": "Wii ISOs",                 "lang": "multi"},
    ],
}

# ROM file extensions per console
from .scanner import CONSOLE_EXTENSIONS

_CLEAN_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*|\.(iso|cso|nds|gba|sfc|smc|z64|n64|v64|bin|nes|md|smd|gg|wbfs|pbp|vpk|pkg|3ds|cia|gbc|gb|cue)$", re.IGNORECASE)


def _clean_name(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name)
    name = name.replace("_", " ").replace(".", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name


async def get_collection_files(identifier: str, console: str) -> list[dict]:
    """Fetch file list from Archive.org for a given item identifier."""
    extensions = set(CONSOLE_EXTENSIONS.get(console, []))
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"https://archive.org/metadata/{identifier}/files")
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return [{"error": str(e)}]

    files = []
    for f in data.get("result", []):
        name = f.get("name", "")
        if not any(name.lower().endswith(ext) for ext in extensions):
            continue
        # Skip sub-directories, metadata files
        if "/" in name:
            name = name.split("/")[-1]
        size = int(f.get("size", 0))
        files.append({
            "filename": name,
            "title": _clean_name(name),
            "size": size,
            "url": f"https://archive.org/download/{identifier}/{f.get('name', name)}",
            "collection": identifier,
        })

    return sorted(files, key=lambda x: x["title"].lower())


async def search_archive_global(query: str, console: str) -> list[dict]:
    """Search Archive.org full text for ROM files matching query + console."""
    extensions = CONSOLE_EXTENSIONS.get(console, [])
    if not extensions:
        return []
    ext_str = " OR ".join(f'*.{e.lstrip(".")}' for e in extensions)
    q = f'title:("{query}") AND mediatype:(software OR data) AND format:(ROM OR ISO)'
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": q,
                    "output": "json",
                    "fl[]": ["identifier", "title", "description", "downloads"],
                    "rows": 12,
                    "sort[]": "downloads desc",
                },
            )
            data = r.json()
        docs = data.get("response", {}).get("docs", [])
        results = []
        for d in docs:
            results.append({
                "identifier": d.get("identifier"),
                "title": d.get("title", d.get("identifier")),
                "description": (d.get("description") or "")[:120],
                "downloads": d.get("downloads", 0),
                "browse_url": f"https://archive.org/details/{d.get('identifier')}",
            })
        return results
    except Exception:
        return []
