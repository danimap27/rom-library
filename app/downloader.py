import asyncio
import time
import httpx
from pathlib import Path
from .database import add_download, update_download, update_game

ROMS_BASE = Path.home() / "roms"
MAX_CONCURRENT = 3
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_queue_count = 0  # downloads waiting for a slot


async def download_rom(game_id: int, url: str, console: str):
    """Download a ROM with concurrency limit (max 3 at once), speed tracking and auto-retry."""
    global _queue_count
    _queue_count += 1
    update_game(game_id, status="queued")
    try:
        async with _semaphore:
            _queue_count -= 1
            await _do_download(game_id, url, console, attempt=1)
    except Exception:
        _queue_count = max(0, _queue_count - 1)


async def _do_download(game_id: int, url: str, console: str, attempt: int):
    console_path = ROMS_BASE / console
    console_path.mkdir(parents=True, exist_ok=True)

    filename = _extract_filename(url)
    filepath = console_path / filename
    dl_id = add_download(game_id, url)

    try:
        update_download(dl_id, status="downloading", progress=0)
        update_game(game_id, status="downloading")

        headers = {"User-Agent": "Mozilla/5.0 (compatible; ROMLibrary/1.0)"}

        # Resume: if partial file exists, add Range header
        resume_from = 0
        if filepath.exists():
            resume_from = filepath.stat().st_size
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=None, write=None, pool=None),
            headers=headers,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code == 416:
                    # File already complete
                    update_download(dl_id, status="completed", progress=100)
                    update_game(game_id, file_path=str(filepath), status="owned",
                                file_size=filepath.stat().st_size)
                    return

                response.raise_for_status()

                content_range = response.headers.get("content-range", "")
                content_length = int(response.headers.get("content-length", 0))

                if content_range and resume_from > 0:
                    total = int(content_range.split("/")[-1]) if "/" in content_range else 0
                    downloaded = resume_from
                    mode = "ab"
                else:
                    total = content_length
                    downloaded = 0
                    resume_from = 0
                    mode = "wb"

                t_start = time.monotonic()
                last_update = t_start
                last_downloaded = downloaded

                with open(filepath, mode) as f:
                    async for chunk in response.aiter_bytes(chunk_size=131072):
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.monotonic()
                        if now - last_update >= 1.0:
                            speed = (downloaded - last_downloaded) / (now - last_update)
                            progress = min(int(downloaded / total * 100), 99) if total else 0
                            eta = int((total - downloaded) / speed) if speed > 0 and total > downloaded else 0
                            update_download(dl_id, status="downloading", progress=progress,
                                            speed=int(speed), eta=eta,
                                            downloaded=downloaded, total_size=total)
                            last_update = now
                            last_downloaded = downloaded

        update_download(dl_id, status="completed", progress=100, speed=0, eta=0)
        update_game(game_id, file_path=str(filepath), status="owned",
                    file_size=filepath.stat().st_size)

    except httpx.HTTPStatusError as e:
        if attempt < 2 and e.response.status_code >= 500:
            await asyncio.sleep(5)
            await _do_download(game_id, url, console, attempt + 1)
            return
        _mark_failed(dl_id, game_id, f"HTTP {e.response.status_code}")

    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        if attempt < 2:
            await asyncio.sleep(10)
            await _do_download(game_id, url, console, attempt + 1)
            return
        _mark_failed(dl_id, game_id, str(e)[:120])

    except Exception as e:
        _mark_failed(dl_id, game_id, str(e)[:120])


def _mark_failed(dl_id: int, game_id: int, error: str):
    update_download(dl_id, status="failed", error=error)
    update_game(game_id, status="failed")


def _extract_filename(url: str) -> str:
    from urllib.parse import urlparse, unquote
    path = urlparse(url).path
    name = unquote(path.split("/")[-1]).split("?")[0]
    return name if name and "." in name else "rom_download.bin"


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
