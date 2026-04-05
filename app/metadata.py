"""
IGDB metadata fetcher (optional).
Set IGDB_CLIENT_ID and IGDB_CLIENT_SECRET in .env to enable.
Get credentials free at: https://dev.twitch.tv/console/apps
"""
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

CLIENT_ID = os.getenv("IGDB_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "")

_token_cache: dict = {}

CONSOLE_IGDB_IDS = {
    "PSP": 38,
    "PSVita": 46,
    "NintendoDS": 20,
    "Nintendo3DS": 37,
    "GBA": 24,
    "GBC": 22,
    "GB": 33,
    "NES": 18,
    "SNES": 19,
    "N64": 4,
    "PS1": 7,
    "PS2": 8,
    "GameCube": 21,
    "Wii": 5,
    "MegaDrive": 29,
    "GameGear": 35,
}

GENRE_MAP = {
    0: "Punto y clic", 2: "Plataformas", 4: "Deportes", 5: "Simulador",
    7: "Puzzle", 8: "Arcade", 9: "Shooter", 10: "Aventura",
    11: "Música", 12: "Rol (RPG)", 13: "Estrategia", 14: "Lucha",
    15: "Aventura gráfica", 16: "Acción", 24: "Carreras", 25: "Beat em up",
    26: "Trivia", 30: "Pinball", 31: "Aventura", 32: "Indie",
    33: "Arcade", 34: "Visual novel",
}


async def _get_token() -> str:
    if _token_cache.get("token") and _token_cache.get("expires", 0) > __import__("time").time():
        return _token_cache["token"]
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://id.twitch.tv/oauth2/token",
            params={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                    "grant_type": "client_credentials"},
        )
        data = r.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires"] = __import__("time").time() + data["expires_in"] - 60
    return _token_cache["token"]


async def fetch_metadata(game_id: int, title: str, console: str) -> dict | None:
    """Fetch metadata from IGDB and update the game in DB."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return None

    from .database import update_game
    try:
        token = await _get_token()
        platform_id = CONSOLE_IGDB_IDS.get(console)

        query = f'search "{title}"; fields name,cover.url,genres,first_release_date,summary;'
        if platform_id:
            query += f' where platforms = ({platform_id});'
        query += " limit 1;"

        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"},
                content=query,
            )
            results = r.json()

        if not results:
            return None

        g = results[0]
        updates = {}

        if "cover" in g:
            url = g["cover"]["url"].replace("t_thumb", "t_cover_big")
            if url.startswith("//"):
                url = "https:" + url
            updates["cover_url"] = url

        if "genres" in g:
            genre_id = g["genres"][0] if g["genres"] else None
            updates["genre"] = GENRE_MAP.get(genre_id, "Otros")

        if "first_release_date" in g:
            import datetime
            updates["year"] = datetime.datetime.fromtimestamp(
                g["first_release_date"]
            ).year

        if "summary" in g:
            updates["description"] = g["summary"][:500]

        if updates:
            update_game(game_id, **updates)

        return updates

    except Exception:
        return None


async def search_covers(title: str, console: str) -> list[dict]:
    """Return list of {title, cover_url, year, genre} from IGDB."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return []
    try:
        token = await _get_token()
        platform_id = CONSOLE_IGDB_IDS.get(console)
        query = f'search "{title}"; fields name,cover.url,genres,first_release_date;'
        if platform_id:
            query += f' where platforms = ({platform_id});'
        query += " limit 8;"

        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.igdb.com/v4/games",
                headers={"Client-ID": CLIENT_ID, "Authorization": f"Bearer {token}"},
                content=query,
            )
            results = r.json()

        out = []
        for g in results:
            cover = g.get("cover", {}).get("url", "")
            if cover.startswith("//"):
                cover = "https:" + cover
            cover = cover.replace("t_thumb", "t_cover_big")
            year = None
            if "first_release_date" in g:
                import datetime
                year = datetime.datetime.fromtimestamp(g["first_release_date"]).year
            genre_id = (g.get("genres") or [None])[0]
            out.append({
                "title": g["name"],
                "cover_url": cover,
                "year": year,
                "genre": GENRE_MAP.get(genre_id, ""),
            })
        return out
    except Exception:
        return []


def is_igdb_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)
