import asyncio
import httpx
from pathlib import Path
from .database import add_download, update_download, update_game

ROMS_BASE = Path.home() / "roms"


async def download_rom(game_id: int, url: str, console: str):
    """Download a ROM file from URL with progress tracking."""
    console_path = ROMS_BASE / console
    console_path.mkdir(parents=True, exist_ok=True)

    filename = _extract_filename(url)
    filepath = console_path / filename
    dl_id = add_download(game_id, url)

    try:
        update_download(dl_id, status="downloading", progress=0)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=None, write=None, pool=None),
            headers={"User-Agent": "Mozilla/5.0 (compatible; ROMLibrary/1.0)"},
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                # Resume support: if partial file exists
                if filepath.exists() and total > 0 and filepath.stat().st_size < total:
                    downloaded = filepath.stat().st_size
                    mode = "ab"
                else:
                    mode = "wb"

                with open(filepath, mode) as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            progress = min(int(downloaded / total * 100), 99)
                            update_download(dl_id, status="downloading", progress=progress)

        update_download(dl_id, status="completed", progress=100)
        update_game(game_id, file_path=str(filepath), status="owned",
                    file_size=filepath.stat().st_size)

    except httpx.HTTPStatusError as e:
        update_download(dl_id, status="failed", error=f"HTTP {e.response.status_code}")
        update_game(game_id, status="failed")
    except Exception as e:
        update_download(dl_id, status="failed", error=str(e)[:200])
        update_game(game_id, status="failed")


def _extract_filename(url: str) -> str:
    """Extract filename from URL, clean it up."""
    from urllib.parse import urlparse, unquote
    path = urlparse(url).path
    name = unquote(path.split("/")[-1])
    # Remove query params if any slipped through
    name = name.split("?")[0]
    if not name or "." not in name:
        name = "rom_download.iso"
    return name


def format_size(size_bytes: int) -> str:
    if not size_bytes:
        return "?"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
