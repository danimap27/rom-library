import sqlite3
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

        -- add columns if upgrading from old schema
        CREATE TABLE IF NOT EXISTS _migrations (id INTEGER PRIMARY KEY, name TEXT UNIQUE);

        """)


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
             cover_url=None, year=None, description=None, file_path=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO games (title, console, genre, region, download_url,
               cover_url, year, description, file_path, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, console, genre, region, download_url,
             cover_url, year, description, file_path,
             "downloading" if download_url else ("owned" if file_path else "pending"))
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
            """SELECT d.*, g.title, g.console FROM downloads d
               JOIN games g ON g.id = d.game_id
               ORDER BY d.created_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def migrate():
    """Add columns to existing DBs without breaking them."""
    cols_to_add = [
        ("downloads", "speed", "INTEGER DEFAULT 0"),
        ("downloads", "eta", "INTEGER DEFAULT 0"),
        ("downloads", "downloaded", "INTEGER DEFAULT 0"),
        ("downloads", "total_size", "INTEGER DEFAULT 0"),
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


def get_disk_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT console, COUNT(*) as count, SUM(file_size) as size "
            "FROM games WHERE file_size > 0 GROUP BY console ORDER BY size DESC"
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) as c, SUM(file_size) as s FROM games WHERE file_size > 0"
        ).fetchone()
    return {
        "by_console": [dict(r) for r in rows],
        "total_games": total["c"] or 0,
        "total_size": total["s"] or 0,
    }


def get_active_downloads():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM downloads WHERE status IN ('pending', 'downloading')"
        ).fetchall()
    return [dict(r) for r in rows]
