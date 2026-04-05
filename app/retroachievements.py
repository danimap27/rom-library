"""
RetroAchievements integration (optional).
Set RA_USERNAME and RA_API_KEY in .env to enable.
Get free API key at: https://retroachievements.org/settings
"""
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

RA_USERNAME = os.getenv("RA_USERNAME", "")
RA_API_KEY = os.getenv("RA_API_KEY", "")
RA_BASE = "https://retroachievements.org/API"

# Map our console names to RA console IDs
RA_CONSOLE_IDS = {
    "GB": 4,
    "GBC": 6,
    "GBA": 5,
    "NES": 7,
    "SNES": 3,
    "N64": 2,
    "GameGear": 15,
    "MegaDrive": 1,
    "PS1": 12,
    "PS2": 21,
    "PSP": 41,
    "NintendoDS": 18,
    "Nintendo3DS": 37,
}


def is_configured() -> bool:
    return bool(RA_USERNAME and RA_API_KEY)


async def search_game(title: str, console: str) -> dict | None:
    """Search RetroAchievements for a game, return best match with achievement count."""
    if not is_configured():
        return None
    console_id = RA_CONSOLE_IDS.get(console)
    if not console_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{RA_BASE}/API_GetGameList.php",
                params={"z": RA_USERNAME, "y": RA_API_KEY, "i": console_id},
            )
            games = r.json()
        if not isinstance(games, list):
            return None

        title_lower = title.lower()
        best = None
        best_score = 0
        for g in games:
            g_title = g.get("Title", "").lower()
            # simple substring match scoring
            if title_lower in g_title or g_title in title_lower:
                score = min(len(title_lower), len(g_title)) / max(len(title_lower), len(g_title))
                if score > best_score:
                    best_score = score
                    best = g

        if best and best_score > 0.5:
            return {
                "ra_game_id": best.get("ID"),
                "ra_title": best.get("Title"),
                "ra_achievements": best.get("NumAchievements", 0),
            }
        return None
    except Exception:
        return None


async def get_game_achievements(ra_game_id: int) -> dict | None:
    """Get detailed achievement data for a RA game ID."""
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{RA_BASE}/API_GetGame.php",
                params={"z": RA_USERNAME, "y": RA_API_KEY, "i": ra_game_id},
            )
            data = r.json()
        return {
            "ra_game_id": ra_game_id,
            "ra_title": data.get("Title"),
            "ra_achievements": data.get("NumAchievements", 0),
            "ra_points": data.get("Points", 0),
            "ra_image": data.get("ImageIcon"),
        }
    except Exception:
        return None
