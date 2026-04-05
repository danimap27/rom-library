import re
from pathlib import Path
from urllib.parse import urlparse, unquote
from .database import add_game, get_games, get_disc_group

CONSOLE_EXTENSIONS = {
    "PSP": [".iso", ".cso", ".pbp"],
    "PSVita": [".vpk", ".pkg"],
    "NintendoDS": [".nds"],
    "Nintendo3DS": [".3ds", ".cia", ".cxi"],
    "GBA": [".gba"],
    "GBC": [".gbc"],
    "GB": [".gb"],
    "NES": [".nes"],
    "SNES": [".sfc", ".smc"],
    "N64": [".z64", ".n64", ".v64"],
    "PS1": [".bin", ".cue"],
    "PS2": [".iso"],
    "GameCube": [".iso", ".gcm"],
    "Wii": [".wbfs", ".iso"],
    "MegaDrive": [".md", ".smd"],
    "GameGear": [".gg"],
}

EXT_TO_CONSOLE = {}
for console, exts in CONSOLE_EXTENSIONS.items():
    for ext in exts:
        if ext not in EXT_TO_CONSOLE:
            EXT_TO_CONSOLE[ext] = console


def detect_console_from_path(path: Path) -> str:
    """Detect console from parent folder name first, then file extension."""
    for part in reversed(path.parts[:-1]):
        for console in CONSOLE_EXTENSIONS:
            if console.lower() in part.lower():
                return console
    return EXT_TO_CONSOLE.get(path.suffix.lower(), "Unknown")


def scan_directory(roms_path: Path) -> dict:
    roms_path = Path(roms_path)
    if not roms_path.exists():
        return {"found": 0, "added": 0}

    existing_paths = {g["file_path"] for g in get_games() if g["file_path"]}
    all_extensions = {ext for exts in CONSOLE_EXTENSIONS.values() for ext in exts}

    found = 0
    added = 0

    for file in roms_path.rglob("*"):
        if not file.is_file():
            continue
        if file.suffix.lower() not in all_extensions:
            continue

        found += 1
        file_str = str(file)

        if file_str in existing_paths:
            continue

        console = detect_console_from_path(file)
        raw_title = file.stem.replace("_", " ").replace(".", " ").strip()
        title = clean_title(file.name)
        disc_group, disc_number = get_disc_group(title)

        add_game(
            title=title or raw_title,
            console=console,
            file_path=file_str,
            region=_detect_region(file.name),
            disc_number=disc_number,
            disc_group=disc_group if disc_number else None,
        )
        added += 1

    return {"found": found, "added": added}


def _detect_region(filename: str) -> str:
    fname = filename.lower()
    if any(x in fname for x in ["(spain)", "(es)", "(spa)", "español"]):
        return "ES"
    if any(x in fname for x in ["(europe)", "(eu)", "(eur)"]):
        return "EU"
    if any(x in fname for x in ["(usa)", "(us)", "(ntsc-u)"]):
        return "US"
    if any(x in fname for x in ["(japan)", "(ja)", "(jpn)"]):
        return "JP"
    return "ES"


CONSOLES = list(CONSOLE_EXTENSIONS.keys())


def clean_title(filename: str) -> str:
    """Convert filename to clean game title."""
    name = Path(filename).stem
    # Remove region/version tags like (Spain), (v1.2), [!], etc.
    name = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name)
    name = name.replace("_", " ").replace(".", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name


def url_to_game_info(url: str) -> dict:
    """Extract game info from a download URL, magnet link or .torrent URL."""
    if url.startswith("magnet:"):
        from urllib.parse import parse_qs
        params = parse_qs(url[8:])
        dn_list = params.get("dn", [])
        filename = unquote(dn_list[0]) if dn_list else "torrent_download"
        ext = Path(filename).suffix.lower()
        console = EXT_TO_CONSOLE.get(ext, "Unknown")
        return {
            "title": clean_title(filename) or "Torrent Download",
            "console": console,
            "region": _detect_region(filename),
            "filename": filename,
            "extension": ext,
        }
    parsed = urlparse(url)
    filename = unquote(parsed.path.split("/")[-1])
    ext = Path(filename).suffix.lower()
    console = EXT_TO_CONSOLE.get(ext, "Unknown")
    return {
        "title": clean_title(filename),
        "console": console,
        "region": _detect_region(filename),
        "filename": filename,
        "extension": ext,
    }
