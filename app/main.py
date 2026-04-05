import asyncio
from pathlib import Path
from fastapi import FastAPI, BackgroundTasks, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import (
    init_db, get_games, get_game, add_game, update_game, delete_game,
    get_console_counts, get_genres, get_downloads, get_active_downloads,
    get_disk_stats,
)
from .scanner import scan_directory, CONSOLES, CONSOLE_EXTENSIONS, url_to_game_info
from .downloader import download_rom, format_size, format_speed, format_eta, queue_status, aria2_version
from .metadata import fetch_metadata, is_igdb_configured, search_covers

BASE_DIR = Path(__file__).parent.parent
ROMS_PATH = Path.home() / "roms"

app = FastAPI(title="ROM Library")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/covers", StaticFiles(directory=BASE_DIR / "covers"), name="covers")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["format_size"] = format_size

_CONSOLE_EMOJI = {
    "PSP": "🎮", "PSVita": "🎮", "NintendoDS": "📺", "Nintendo3DS": "📺",
    "GBA": "🕹️", "GBC": "🕹️", "GB": "🕹️", "NES": "🎯", "SNES": "🎯",
    "N64": "🏆", "PS1": "🎮", "PS2": "🎮", "GameCube": "🎲", "Wii": "🎲",
    "MegaDrive": "⚡", "GameGear": "⚡",
}
_STATUS_ICON = {"owned": "✅", "downloading": "⬇️", "pending": "⏳", "failed": "❌"}

templates.env.globals["console_emoji"] = lambda c: _CONSOLE_EMOJI.get(c, "🎮")
templates.env.globals["status_icon"] = lambda s: _STATUS_ICON.get(s, "❓")
templates.env.globals["igdb_enabled"] = is_igdb_configured
templates.env.globals["format_speed"] = format_speed
templates.env.globals["format_eta"] = format_eta


@app.on_event("startup")
async def startup():
    init_db()
    ROMS_PATH.mkdir(parents=True, exist_ok=True)
    for console in CONSOLE_EXTENSIONS:
        (ROMS_PATH / console).mkdir(parents=True, exist_ok=True)


# ── HTML ──────────────────────────────────────────────────────────────────────

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


# ── API Games ─────────────────────────────────────────────────────────────────

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
):
    game_id = add_game(
        title=title, console=console, genre=genre, region=region,
        year=year, cover_url=cover_url, description=description,
        download_url=download_url,
    )
    if download_url and download_url.strip():
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
    if download_url and download_url.strip():
        game = get_game(game_id)
        if game:
            background_tasks.add_task(download_rom, game_id, download_url.strip(), game["console"])
    return {"status": "updated"}


@app.delete("/api/games/{game_id}")
async def api_delete_game(game_id: int):
    delete_game(game_id)
    return {"status": "deleted"}


# ── API Downloads ─────────────────────────────────────────────────────────────

@app.get("/api/downloads")
async def api_downloads():
    return get_downloads(50)


# ── API Scan ──────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def api_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_directory, ROMS_PATH)
    return {"status": "scanning", "path": str(ROMS_PATH)}


# ── Quick Add (URL → auto-detect todo) ───────────────────────────────────────

@app.post("/api/quick-add")
async def api_quick_add(background_tasks: BackgroundTasks, url: str = Form(...)):
    """Paste a direct download URL, magnet link or .torrent URL → download via aria2."""
    url = url.strip()
    if not (url.startswith("http") or url.startswith("magnet:") or url.startswith("ftp")):
        return JSONResponse({"error": "URL no válida"}, status_code=400)
    info = url_to_game_info(url)
    game_id = add_game(
        title=info["title"],
        console=info["console"],
        region=info["region"],
        download_url=url,
    )
    background_tasks.add_task(download_rom, game_id, url, info["console"])
    background_tasks.add_task(fetch_metadata, game_id, info["title"], info["console"])
    return {"id": game_id, "title": info["title"], "console": info["console"],
            "region": info["region"], "status": "downloading"}


@app.post("/api/bulk-add")
async def api_bulk_add(background_tasks: BackgroundTasks, urls: str = Form(...)):
    """One URL per line → add and download all."""
    lines = [u.strip() for u in urls.splitlines() if u.strip().startswith("http")]
    added = []
    for url in lines:
        info = url_to_game_info(url)
        game_id = add_game(
            title=info["title"],
            console=info["console"],
            region=info["region"],
            download_url=url,
        )
        background_tasks.add_task(download_rom, game_id, url, info["console"])
        background_tasks.add_task(fetch_metadata, game_id, info["title"], info["console"])
        added.append({"id": game_id, "title": info["title"], "console": info["console"]})
    return {"added": len(added), "games": added}


@app.get("/api/stats")
async def api_stats():
    counts = get_console_counts()
    disk = get_disk_stats()
    all_games = get_games()
    statuses = {}
    for g in all_games:
        s = g["status"] or "unknown"
        statuses[s] = statuses.get(s, 0) + 1
    return {
        "total": len(all_games),
        "by_console": counts,
        "by_status": statuses,
        "disk": disk,
        "queue": queue_status(),
    }


@app.get("/sources", response_class=HTMLResponse)
async def sources(request: Request):
    return templates.TemplateResponse("sources.html", {
        "request": request,
        "consoles": CONSOLES,
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


@app.get("/api/covers/search")
async def api_cover_search(q: str, console: str = ""):
    results = await search_covers(q, console)
    return results


@app.get("/api/aria2/status")
async def api_aria2_status():
    version = await aria2_version()
    return {"online": version is not None, "version": version}


@app.get("/api/downloads/active")
async def api_active_downloads_with_speed():
    rows = get_active_downloads()
    return [
        {**r, "speed_str": format_speed(r.get("speed", 0)),
         "eta_str": format_eta(r.get("eta", 0))}
        for r in rows
    ]
