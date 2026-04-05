import sqlite3
import re
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "rom-library.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    migrate()
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            console TEXT NOT NULL,
            genre TEXT,
            region TEXT DEFAULT 'ES',
            status TEXT DEFAULT 'pending',
            file_path TEXT,
            cover_url TEXT,
            download_url TEXT,
            file_size INTEGER,
            year INTEGER,
            rating REAL,
            description TEXT,
            last_played TEXT,
            total_playtime INTEGER DEFAULT 0,
            ra_game_id INTEGER,
            ra_achievements INTEGER,
            ra_total_achievements INTEGER,
            disc_number INTEGER,
            disc_group TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            speed INTEGER DEFAULT 0,
            eta INTEGER DEFAULT 0,
            downloaded INTEGER DEFAULT 0,
            total_size INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS playtime_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_seconds INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS _migrations (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        """)


# ── Queries ────────────────────────────────────────────────────────────────────

def get_games(console=None, search=None, status=None, genre=None):
    query = "SELECT * FROM games WHERE 1=1"
    params = []
    if console:
        query += " AND console = ?"
        params.append(console)
    if search:
        query += " AND title LIKE ?"
        params.append(f"%{search}%")
    if status:
        query += " AND status = ?"
        params.append(status)
    if genre:
        query += " AND genre = ?"
        params.append(genre)
    query += " ORDER BY title COLLATE NOCASE"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_game(game_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    return dict(row) if row else None


def add_game(title, console, genre=None, region="ES", download_url=None,
             cover_url=None, year=None, description=None, file_path=None,
             disc_number=None, disc_group=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO games (title, console, genre, region, download_url,
               cover_url, year, description, file_path, status, disc_number, disc_group)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, console, genre, region, download_url,
             cover_url, year, description, file_path,
             "downloading" if download_url else ("owned" if file_path else "pending"),
             disc_number, disc_group)
        )
    return cur.lastrowid


def update_game(game_id: int, **kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [game_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE games SET {sets} WHERE id = ?", vals)


def delete_game(game_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM games WHERE id = ?", (game_id,))


def get_console_counts():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT console, COUNT(*) as count FROM games GROUP BY console ORDER BY console"
        ).fetchall()
    return {r["console"]: r["count"] for r in rows}


def get_genres():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT genre FROM games WHERE genre IS NOT NULL ORDER BY genre"
        ).fetchall()
    return [r["genre"] for r in rows]


# ── Downloads ──────────────────────────────────────────────────────────────────

def add_download(game_id: int, url: str):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO downloads (game_id, url) VALUES (?, ?)", (game_id, url)
        )
    return cur.lastrowid


def update_download(download_id: int, **kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [download_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE downloads SET {sets} WHERE id = ?", vals)


def get_downloads(limit=20):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT d.*, g.title, g.console, g.id as game_id FROM downloads d
               JOIN games g ON g.id = d.game_id
               ORDER BY d.created_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_downloads():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM downloads WHERE status IN ('pending', 'downloading')"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Playtime ───────────────────────────────────────────────────────────────────

def start_playtime_session(game_id: int) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO playtime_sessions (game_id, started_at) VALUES (?, ?)",
            (game_id, now)
        )
        conn.execute(
            "UPDATE games SET last_played = ?, updated_at = ? WHERE id = ?",
            (now, now, game_id)
        )
    return cur.lastrowid


def stop_playtime_session(session_id: int) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM playtime_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return 0
        started = datetime.fromisoformat(row["started_at"])
        duration = max(0, int((datetime.now() - started).total_seconds()))
        conn.execute(
            "UPDATE playtime_sessions SET ended_at = ?, duration_seconds = ? WHERE id = ?",
            (now, duration, session_id)
        )
        conn.execute(
            "UPDATE games SET total_playtime = COALESCE(total_playtime, 0) + ?, updated_at = ? WHERE id = ?",
            (duration, now, row["game_id"])
        )
    return duration


def get_playtime_sessions(game_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM playtime_sessions WHERE game_id = ? ORDER BY started_at DESC LIMIT 20",
            (game_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Duplicates ─────────────────────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Strip region/version tags and lowercase for comparison."""
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", title)
    t = re.sub(r"[_\-\.\s]+", " ", t).strip().lower()
    return t


def find_duplicates() -> list[dict]:
    """Return groups of games that look like duplicates (same console + normalized title)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, title, console, status, file_size FROM games").fetchall()
    games = [dict(r) for r in rows]

    groups: dict[str, list] = {}
    for g in games:
        key = f"{g['console']}|{_normalize_title(g['title'])}"
        groups.setdefault(key, []).append(g)

    return [
        {"key": k, "games": v}
        for k, v in groups.items()
        if len(v) > 1
    ]


# ── Multi-disc detection ───────────────────────────────────────────────────────

_DISC_RE = re.compile(
    r"[\s\-_]*\(?"
    r"(?:disc|disk|cd|lado|side)\s*(\d+)"
    r"\)?",
    re.IGNORECASE
)


def get_disc_group(title: str) -> tuple[str, int | None]:
    """Return (base_title, disc_number) or (title, None) if not multi-disc."""
    m = _DISC_RE.search(title)
    if m:
        disc_num = int(m.group(1))
        base = title[:m.start()].strip()
        return base, disc_num
    return title, None


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_disk_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT console, COUNT(*) as count, SUM(file_size) as size "
            "FROM games WHERE file_size > 0 GROUP BY console ORDER BY size DESC"
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) as c, SUM(file_size) as s FROM games WHERE file_size > 0"
        ).fetchone()
        playtime_total = conn.execute(
            "SELECT SUM(total_playtime) as t FROM games"
        ).fetchone()
    return {
        "by_console": [dict(r) for r in rows],
        "total_games": total["c"] or 0,
        "total_size": total["s"] or 0,
        "total_playtime_seconds": playtime_total["t"] or 0,
    }


def get_full_stats() -> dict:
    counts = get_console_counts()
    disk = get_disk_stats()
    all_games = get_games()
    statuses: dict[str, int] = {}
    genres: dict[str, int] = {}
    for g in all_games:
        s = g["status"] or "unknown"
        statuses[s] = statuses.get(s, 0) + 1
        if g.get("genre"):
            genres[g["genre"]] = genres.get(g["genre"], 0) + 1

    recently_played = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM games WHERE last_played IS NOT NULL ORDER BY last_played DESC LIMIT 10"
        ).fetchall()
        recently_played = [dict(r) for r in rows]

    top_playtime = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM games WHERE total_playtime > 0 ORDER BY total_playtime DESC LIMIT 10"
        ).fetchall()
        top_playtime = [dict(r) for r in rows]

    return {
        "total": len(all_games),
        "by_console": counts,
        "by_status": statuses,
        "by_genre": dict(sorted(genres.items(), key=lambda x: x[1], reverse=True)[:10]),
        "disk": disk,
        "recently_played": recently_played,
        "top_playtime": top_playtime,
    }


# ── Export ─────────────────────────────────────────────────────────────────────

def export_games_as_list() -> list[dict]:
    return get_games()


# ── Migrations ─────────────────────────────────────────────────────────────────

def migrate():
    """Add columns to existing DBs without breaking them."""
    cols_to_add = [
        ("downloads", "speed", "INTEGER DEFAULT 0"),
        ("downloads", "eta", "INTEGER DEFAULT 0"),
        ("downloads", "downloaded", "INTEGER DEFAULT 0"),
        ("downloads", "total_size", "INTEGER DEFAULT 0"),
        ("games", "last_played", "TEXT"),
        ("games", "total_playtime", "INTEGER DEFAULT 0"),
        ("games", "ra_game_id", "INTEGER"),
        ("games", "ra_achievements", "INTEGER"),
        ("games", "ra_total_achievements", "INTEGER"),
        ("games", "disc_number", "INTEGER"),
        ("games", "disc_group", "TEXT"),
    ]
    with get_conn() as conn:
        existing = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT m.name, p.name FROM sqlite_master m "
                "JOIN pragma_table_info(m.name) p WHERE m.type='table'"
            ).fetchall()
        }
        for table, col, typedef in cols_to_add:
            if (table, col) not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
