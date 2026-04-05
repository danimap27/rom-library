"""
ROM downloader — delegated to aria2c via JSON-RPC.
Supports HTTP/HTTPS direct links, .torrent files, and magnet: URIs.
"""
import asyncio
import time
import httpx
from pathlib import Path
from .database import add_download, update_download, update_game

ROMS_BASE = Path.home() / "roms"
ARIA2_RPC = "http://localhost:6800/jsonrpc"
ARIA2_TOKEN = "token:romlibrary2025"

# ── Aria2 RPC helpers ──────────────────────────────────────────────────────────

async def _rpc(method: str, params: list) -> dict:
    payload = {"jsonrpc": "2.0", "method": method, "id": "rl", "params": [ARIA2_TOKEN] + params}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ARIA2_RPC, json=payload)
        return r.json()


async def _add_uri(url: str, dest_dir: str) -> str | None:
    """Add HTTP/HTTPS/FTP/magnet URL to aria2. Returns GID or None on error."""
    opts = {"dir": dest_dir, "max-connection-per-server": "4", "split": "4", "continue": "true"}
    res = await _rpc("aria2.addUri", [[url], opts])
    return res.get("result")


async def _add_torrent(torrent_b64: str, dest_dir: str) -> str | None:
    opts = {"dir": dest_dir, "seed-time": "0"}
    res = await _rpc("aria2.addTorrent", [torrent_b64, [], opts])
    return res.get("result")


async def _get_status(gid: str) -> dict:
    res = await _rpc("aria2.tellStatus", [gid, [
        "status", "completedLength", "totalLength", "downloadSpeed",
        "errorMessage", "files", "bittorrent"
    ]])
    return res.get("result", {})


async def _remove(gid: str):
    await _rpc("aria2.remove", [gid])
    await _rpc("aria2.removeDownloadResult", [gid])


# ── GID tracking (game_id → aria2 GID) ────────────────────────────────────────
_game_gid: dict[int, str] = {}


def get_game_gid(game_id: int) -> str | None:
    return _game_gid.get(game_id)


# ── Public interface ───────────────────────────────────────────────────────────

MAX_CONCURRENT = 3
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_queue_count = 0


async def download_rom(game_id: int, url: str, console: str):
    """Queue a download through aria2. Accepts HTTP, magnet:, or .torrent URLs."""
    global _queue_count
    _queue_count += 1
    update_game(game_id, status="queued")
    try:
        async with _semaphore:
            _queue_count -= 1
            await _do_aria2_download(game_id, url, console)
    except Exception:
        _queue_count = max(0, _queue_count - 1)


async def _do_aria2_download(game_id: int, url: str, console: str):
    dest_dir = str(ROMS_BASE / console)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    dl_id = add_download(game_id, url)

    # Handle .torrent file URLs: download the .torrent first, then add it
    if url.lower().endswith(".torrent") and url.startswith("http"):
        gid = await _add_torrent_from_url(url, dest_dir, game_id, dl_id)
    else:
        gid = await _add_uri(url, dest_dir)

    if not gid:
        update_download(dl_id, status="failed", error="aria2 rechazó la URL")
        update_game(game_id, status="failed")
        return

    _game_gid[game_id] = gid
    update_download(dl_id, status="downloading", progress=0)
    update_game(game_id, status="downloading")

    await _poll_aria2(gid, game_id, dl_id, console)
    _game_gid.pop(game_id, None)


async def _add_torrent_from_url(url: str, dest_dir: str, game_id: int, dl_id: int) -> str | None:
    import base64
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
        encoded = base64.b64encode(r.content).decode()
        return await _add_torrent(encoded, dest_dir)
    except Exception as e:
        update_download(dl_id, status="failed", error=f"torrent fetch: {e}"[:100])
        update_game(game_id, status="failed")
        return None


async def _poll_aria2(gid: str, game_id: int, dl_id: int, console: str):
    """Poll aria2 status until complete/error, updating DB progress."""
    while True:
        await asyncio.sleep(2)
        try:
            st = await _get_status(gid)
        except Exception:
            await asyncio.sleep(5)
            continue

        status = st.get("status", "")
        completed = int(st.get("completedLength", 0))
        total = int(st.get("totalLength", 0))
        speed = int(st.get("downloadSpeed", 0))
        progress = min(int(completed / total * 100), 99) if total > 0 else 0
        eta = int((total - completed) / speed) if speed > 0 and total > completed else 0

        if status in ("active", "waiting", "paused"):
            update_download(dl_id, status="downloading", progress=progress,
                            speed=speed, eta=eta, downloaded=completed, total_size=total)
            update_game(game_id, status="downloading")

        elif status == "complete":
            file_path = _get_file_path(st)
            update_download(dl_id, status="completed", progress=100, speed=0, eta=0)
            update_game(game_id, status="owned",
                        file_path=file_path,
                        file_size=completed or total)
            break

        elif status == "error":
            err = st.get("errorMessage", "Error desconocido")[:120]
            update_download(dl_id, status="failed", error=err)
            update_game(game_id, status="failed")
            break

        else:
            # removed/unknown — give up
            update_download(dl_id, status="failed", error=f"aria2 status: {status}")
            update_game(game_id, status="failed")
            break


def _get_file_path(st: dict) -> str:
    files = st.get("files", [])
    if files:
        return files[0].get("path", "")
    return ""


# ── Aria2 health check ─────────────────────────────────────────────────────────

async def aria2_pause(gid: str):
    await _rpc("aria2.pause", [gid])


async def aria2_resume(gid: str):
    await _rpc("aria2.unpause", [gid])


async def aria2_cancel(gid: str):
    await _rpc("aria2.remove", [gid])
    await _rpc("aria2.removeDownloadResult", [gid])


async def aria2_global_stats() -> dict:
    try:
        res = await _rpc("aria2.getGlobalStat", [])
        r = res.get("result", {})
        return {
            "active": int(r.get("numActive", 0)),
            "waiting": int(r.get("numWaiting", 0)),
            "stopped": int(r.get("numStoppedTotal", 0)),
            "download_speed": int(r.get("downloadSpeed", 0)),
        }
    except Exception:
        return {}


async def aria2_version() -> str | None:
    """Return aria2 version string or None if unreachable."""
    try:
        res = await _rpc("aria2.getVersion", [])
        return res.get("result", {}).get("version")
    except Exception:
        return None


# ── Formatters ─────────────────────────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    if not size_bytes:
        return "?"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


def format_speed(bps: int) -> str:
    if not bps:
        return ""
    if bps < 1024:
        return f"{bps} B/s"
    if bps < 1024 * 1024:
        return f"{bps/1024:.0f} KB/s"
    return f"{bps/1024/1024:.1f} MB/s"


def format_eta(seconds: int) -> str:
    if not seconds or seconds > 86400:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    return f"{seconds//3600}h {(seconds%3600)//60}m"


def queue_status() -> dict:
    return {
        "active": MAX_CONCURRENT - _semaphore._value,
        "queued": _queue_count,
        "max": MAX_CONCURRENT,
    }
