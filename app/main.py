import csv
import json
import asyncio
from io import StringIO
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import (
    init_db, get_games, get_game, add_game, update_game, delete_game,
    get_console_counts, get_genres, get_downloads, get_active_downloads,
    get_disk_stats, get_full_stats, find_duplicates,
    start_playtime_session, stop_playtime_session, get_playtime_sessions,
    export_games_as_list, get_disc_group,
)
from .scanner import scan_directory, CONSOLES, CONSOLE_EXTENSIONS, url_to_game_info
from .downloader import (
    download_rom, format_size, format_speed, format_eta,
    queue_status, aria2_version, aria2_pause, aria2_resume, aria2_cancel,
    aria2_global_stats, get_game_gid,
)
from .metadata import fetch_metadata, is_igdb_configured, search_covers
from .watcher import start_watcher, get_status as watcher_status
from .retroachievements import is_configured as ra_configured, search_game as ra_search, get_game_achievements
from .rom_store import (
    ARCHIVE_COLLECTIONS, get_collection_files, get_all_console_files,
    search_by_name, search_archive_global, build_pack,
)

BASE_DIR = Path(__file__).parent.parent
ROMS_PATH = Path.home() / "roms"

app = FastAPI(title="ROM Library")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/covers", StaticFiles(directory=BASE_DIR / "covers"), name="covers")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["format_size"] = format_size
templates.env.filters["format_size"] = format_size

_CONSOLE_EMOJI = {
    "PSP": "🎮", "PSVita": "🎮", "NintendoDS": "📺", "Nintendo3DS": "📺",
    "GBA": "🕹️", "GBC": "🕹️", "GB": "🕹️", "NES": "🎯", "SNES": "🎯",
    "N64": "🏆", "PS1": "🎮", "PS2": "🎮", "GameCube": "🎲", "Wii": "🎲",
    "MegaDrive": "⚡", "GameGear": "⚡",
}
_STATUS_ICON = {
    "owned": "✅", "downloading": "⬇️", "pending": "⏳",
    "failed": "❌", "queued": "🕐", "wishlist": "⭐",
}

templates.env.globals["console_emoji"] = lambda c: _CONSOLE_EMOJI.get(c, "🎮")
templates.env.globals["status_icon"] = lambda s: _STATUS_ICON.get(s, "❓")
templates.env.globals["igdb_enabled"] = is_igdb_configured
templates.env.globals["ra_enabled"] = ra_configured
templates.env.globals["format_speed"] = format_speed
templates.env.globals["format_eta"] = format_eta


def _format_playtime(seconds: int) -> str:
    if not seconds:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


templates.env.globals["format_playtime"] = _format_playtime
templates.env.filters["format_playtime"] = _format_playtime


@app.on_event("startup")
async def startup():
    init_db()
    ROMS_PATH.mkdir(parents=True, exist_ok=True)
    for console in CONSOLE_EXTENSIONS:
        (ROMS_PATH / console).mkdir(parents=True, exist_ok=True)
    start_watcher(ROMS_PATH)


# ── HTML pages ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, console: str = None, search: str = None,
                genre: str = None, status: str = None):
    games = get_games(console=console, search=search, status=status, genre=genre)
    counts = get_console_counts()
    total = sum(counts.values())
    return templates.TemplateResponse("index.html", {
        "request": request,
        "games": games,
        "consoles": CONSOLES,
        "console_counts": counts,
        "genres": get_genres(),
        "selected_console": console,
        "selected_genre": genre,
        "selected_status": status,
        "search": search or "",
        "total": total,
    })


@app.get("/archive", response_class=HTMLResponse)
async def archive(request: Request, console: str = None):
    counts = get_console_counts()
    disk = get_disk_stats()
    games = get_games(console=console, status="owned")
    all_games = get_games(status="owned")
    return templates.TemplateResponse("archive.html", {
        "request": request,
        "consoles": CONSOLES,
        "console_counts": counts,
        "disk": disk,
        "games": games,
        "total_owned": len(all_games),
        "selected_console": console,
    })


@app.get("/custom-roms", response_class=HTMLResponse)
async def custom_roms(request: Request, console: str = None):
    return templates.TemplateResponse("custom_roms.html", {
        "request": request,
        "consoles": CONSOLES,
        "selected_console": console,
    })


@app.get("/sources", response_class=HTMLResponse)
async def sources(request: Request):
    return templates.TemplateResponse("sources.html", {
        "request": request,
        "consoles": CONSOLES,
    })


@app.get("/wishlist", response_class=HTMLResponse)
async def wishlist(request: Request, console: str = None):
    games = get_games(console=console, status="wishlist")
    counts = get_console_counts()
    return templates.TemplateResponse("wishlist.html", {
        "request": request,
        "games": games,
        "consoles": CONSOLES,
        "console_counts": counts,
        "selected_console": console,
        "total": len(get_games()),
    })


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    stats = get_full_stats()
    duplicates = find_duplicates()
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "stats": stats,
        "duplicates": duplicates,
        "consoles": CONSOLES,
        "total": stats["total"],
    })


# ── API Games ──────────────────────────────────────────────────────────────────

@app.get("/api/games")
async def api_get_games(console: str = None, search: str = None,
                        status: str = None, genre: str = None):
    return get_games(console=console, search=search, status=status, genre=genre)


@app.get("/api/games/{game_id}")
async def api_get_game(game_id: int):
    game = get_game(game_id)
    if not game:
        return JSONResponse({"error": "not found"}, status_code=404)
    return game


@app.post("/api/games")
async def api_add_game(
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    console: str = Form(...),
    genre: str = Form(None),
    region: str = Form("ES"),
    year: int = Form(None),
    cover_url: str = Form(None),
    description: str = Form(None),
    download_url: str = Form(None),
    status: str = Form(None),
):
    disc_group, disc_number = get_disc_group(title)
    game_id = add_game(
        title=title, console=console, genre=genre, region=region,
        year=year, cover_url=cover_url, description=description,
        download_url=download_url,
        disc_number=disc_number,
        disc_group=disc_group if disc_number else None,
    )
    if status == "wishlist":
        update_game(game_id, status="wishlist")
    elif download_url and download_url.strip():
        background_tasks.add_task(download_rom, game_id, download_url.strip(), console)
    return {"id": game_id, "status": "created"}


@app.put("/api/games/{game_id}")
async def api_update_game(
    game_id: int,
    background_tasks: BackgroundTasks,
    title: str = Form(None),
    console: str = Form(None),
    genre: str = Form(None),
    region: str = Form(None),
    year: int = Form(None),
    cover_url: str = Form(None),
    description: str = Form(None),
    download_url: str = Form(None),
    status: str = Form(None),
):
    fields = {k: v for k, v in {
        "title": title, "console": console, "genre": genre,
        "region": region, "year": year, "cover_url": cover_url,
        "description": description, "download_url": download_url,
        "status": status,
    }.items() if v is not None}
    if fields:
        update_game(game_id, **fields)
    if download_url and download_url.strip() and status != "wishlist":
        game = get_game(game_id)
        if game:
            background_tasks.add_task(download_rom, game_id, download_url.strip(), game["console"])
    return {"status": "updated"}


@app.delete("/api/games/{game_id}")
async def api_delete_game(game_id: int):
    delete_game(game_id)
    return {"status": "deleted"}


# ── Playtime ───────────────────────────────────────────────────────────────────

@app.post("/api/games/{game_id}/play/start")
async def api_play_start(game_id: int):
    game = get_game(game_id)
    if not game:
        return JSONResponse({"error": "not found"}, status_code=404)
    session_id = start_playtime_session(game_id)
    return {"session_id": session_id}


@app.post("/api/games/{game_id}/play/stop")
async def api_play_stop(game_id: int, session_id: int = Form(...)):
    duration = stop_playtime_session(session_id)
    return {"duration_seconds": duration, "duration_str": _format_playtime(duration)}


@app.get("/api/games/{game_id}/playtime")
async def api_game_playtime(game_id: int):
    sessions = get_playtime_sessions(game_id)
    game = get_game(game_id)
    return {
        "total_seconds": game.get("total_playtime", 0) if game else 0,
        "sessions": sessions,
    }


# ── RetroAchievements ──────────────────────────────────────────────────────────

@app.post("/api/games/{game_id}/ra/sync")
async def api_ra_sync(game_id: int):
    game = get_game(game_id)
    if not game:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not ra_configured():
        return JSONResponse({"error": "RetroAchievements no configurado"}, status_code=400)
    result = await ra_search(game["title"], game["console"])
    if result:
        update_game(game_id,
                    ra_game_id=result["ra_game_id"],
                    ra_achievements=result["ra_achievements"])
        return result
    return JSONResponse({"error": "Juego no encontrado en RetroAchievements"}, status_code=404)


@app.get("/api/games/{game_id}/ra")
async def api_ra_info(game_id: int):
    game = get_game(game_id)
    if not game or not game.get("ra_game_id"):
        return JSONResponse({"error": "sin datos RA"}, status_code=404)
    data = await get_game_achievements(game["ra_game_id"])
    return data or JSONResponse({"error": "RA error"}, status_code=502)


# ── Downloads ──────────────────────────────────────────────────────────────────

@app.get("/api/downloads")
async def api_downloads():
    return get_downloads(50)


@app.get("/api/downloads/active")
async def api_active_downloads_with_speed():
    rows = get_active_downloads()
    return [
        {**r, "speed_str": format_speed(r.get("speed", 0)),
         "eta_str": format_eta(r.get("eta", 0))}
        for r in rows
    ]


# ── Scan ───────────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def api_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_directory, ROMS_PATH)
    return {"status": "scanning", "path": str(ROMS_PATH)}


# ── Quick Add ──────────────────────────────────────────────────────────────────

@app.post("/api/quick-add")
async def api_quick_add(background_tasks: BackgroundTasks, url: str = Form(...)):
    url = url.strip()
    if not (url.startswith("http") or url.startswith("magnet:") or url.startswith("ftp")):
        return JSONResponse({"error": "URL no válida"}, status_code=400)
    info = url_to_game_info(url)
    disc_group, disc_number = get_disc_group(info["title"])
    game_id = add_game(
        title=info["title"],
        console=info["console"],
        region=info["region"],
        download_url=url,
        disc_number=disc_number,
        disc_group=disc_group if disc_number else None,
    )
    background_tasks.add_task(download_rom, game_id, url, info["console"])
    background_tasks.add_task(fetch_metadata, game_id, info["title"], info["console"])
    return {"id": game_id, "title": info["title"], "console": info["console"],
            "region": info["region"], "status": "downloading"}


@app.post("/api/bulk-add")
async def api_bulk_add(background_tasks: BackgroundTasks, urls: str = Form(...)):
    lines = [u.strip() for u in urls.splitlines() if u.strip().startswith("http")]
    added = []
    for url in lines:
        info = url_to_game_info(url)
        disc_group, disc_number = get_disc_group(info["title"])
        game_id = add_game(
            title=info["title"],
            console=info["console"],
            region=info["region"],
            download_url=url,
            disc_number=disc_number,
            disc_group=disc_group if disc_number else None,
        )
        background_tasks.add_task(download_rom, game_id, url, info["console"])
        background_tasks.add_task(fetch_metadata, game_id, info["title"], info["console"])
        added.append({"id": game_id, "title": info["title"], "console": info["console"]})
    return {"added": len(added), "games": added}


# ── Stats API ──────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    stats = get_full_stats()
    stats["queue"] = queue_status()
    return stats


@app.get("/api/duplicates")
async def api_duplicates():
    return find_duplicates()


# ── Export ─────────────────────────────────────────────────────────────────────

@app.get("/api/export.json")
async def api_export_json():
    games = export_games_as_list()
    content = json.dumps(games, indent=2, ensure_ascii=False)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=rom-library.json"},
    )


@app.get("/api/export.csv")
async def api_export_csv():
    games = export_games_as_list()
    output = StringIO()
    if games:
        writer = csv.DictWriter(output, fieldnames=games[0].keys())
        writer.writeheader()
        writer.writerows(games)
    content = output.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rom-library.csv"},
    )


# ── Aria2 ──────────────────────────────────────────────────────────────────────

@app.get("/api/aria2/status")
async def api_aria2_status():
    version = await aria2_version()
    stats = await aria2_global_stats() if version else {}
    return {"online": version is not None, "version": version, **stats}


@app.post("/api/aria2/pause/{game_id}")
async def api_aria2_pause(game_id: int):
    gid = get_game_gid(game_id)
    if not gid:
        return JSONResponse({"error": "not found"}, status_code=404)
    await aria2_pause(gid)
    update_game(game_id, status="queued")
    return {"status": "paused"}


@app.post("/api/aria2/resume/{game_id}")
async def api_aria2_resume(game_id: int):
    gid = get_game_gid(game_id)
    if not gid:
        return JSONResponse({"error": "not found"}, status_code=404)
    await aria2_resume(gid)
    update_game(game_id, status="downloading")
    return {"status": "resumed"}


@app.post("/api/aria2/cancel/{game_id}")
async def api_aria2_cancel(game_id: int):
    gid = get_game_gid(game_id)
    if gid:
        await aria2_cancel(gid)
    update_game(game_id, status="failed")
    return {"status": "cancelled"}


# ── Covers ─────────────────────────────────────────────────────────────────────

@app.get("/api/covers/search")
async def api_cover_search(q: str, console: str = ""):
    results = await search_covers(q, console)
    return results


# ── Watcher ────────────────────────────────────────────────────────────────────

@app.get("/api/watcher/status")
async def api_watcher_status():
    return watcher_status()


# ── ROM Store / Browse ──────────────────────────────────────────────────────────

@app.get("/browse", response_class=HTMLResponse)
async def browse(request: Request, console: str = "NintendoDS"):
    collections = ARCHIVE_COLLECTIONS.get(console, [])
    return templates.TemplateResponse("browse.html", {
        "request": request,
        "consoles": CONSOLES,
        "selected_console": console,
        "collections": collections,
        "total": sum(get_console_counts().values()),
        "has_igdb": is_igdb_configured(),
    })


@app.get("/api/browse/files")
async def api_browse_files(identifier: str, console: str):
    return await get_collection_files(identifier, console)


@app.get("/api/browse/search")
async def api_browse_search(q: str, console: str):
    """Search Archive.org items (for extra results panel)."""
    return await search_archive_global(q, console)


@app.get("/api/search/roms")
async def api_search_roms(q: str, console: str):
    """Search for a game by name across all collections for a console."""
    return await search_by_name(q, console)


@app.post("/api/browse/download")
async def api_browse_download(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    title: str = Form(...),
    console: str = Form(...),
):
    """Add a ROM to the download queue + auto-fetch IGDB metadata."""
    disc_group, disc_number = get_disc_group(title)
    game_id = add_game(
        title=title,
        console=console,
        region="EU",
        download_url=url,
        disc_number=disc_number,
        disc_group=disc_group if disc_number else None,
    )
    background_tasks.add_task(download_rom, game_id, url, console)
    background_tasks.add_task(fetch_metadata, game_id, title, console)
    return {"id": game_id, "title": title, "console": console, "status": "queued"}


@app.get("/api/browse/pack")
async def api_browse_pack(
    console: str,
    max_gb: float = 4.0,
    strategy: str = "random",
):
    """Generate a ROM pack: select games to fill target size."""
    all_files = await get_all_console_files(console)
    if not all_files:
        return {"games": [], "total_size": 0, "count": 0, "console": console}
    max_bytes = int(max_gb * 1024 ** 3)
    selected, total = build_pack(all_files, max_bytes, strategy=strategy)
    return {
        "games": selected,
        "total_size": total,
        "count": len(selected),
        "console": console,
        "max_gb": max_gb,
        "available": len(all_files),
    }


@app.post("/api/browse/pack/download")
async def api_browse_pack_download(
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    titles: str = Form(...),
    console: str = Form(...),
):
    """Download all games in a pack (newline-separated urls and titles)."""
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    title_list = [t.strip() for t in titles.splitlines() if t.strip()]
    added = []
    for i, url in enumerate(url_list):
        title = title_list[i] if i < len(title_list) else url.split("/")[-1]
        disc_group, disc_number = get_disc_group(title)
        game_id = add_game(
            title=title, console=console, region="EU", download_url=url,
            disc_number=disc_number, disc_group=disc_group if disc_number else None,
        )
        background_tasks.add_task(download_rom, game_id, url, console)
        background_tasks.add_task(fetch_metadata, game_id, title, console)
        added.append({"id": game_id, "title": title})
    return {"added": len(added), "games": added}
