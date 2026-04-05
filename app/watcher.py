"""
Folder watcher — auto-imports new ROMs dropped into ~/roms/
Requires: watchdog (already in requirements.txt)
"""
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

_status: dict = {
    "active": False,
    "path": None,
    "last_event": None,
    "last_event_at": None,
    "events_count": 0,
    "error": None,
}


def get_status() -> dict:
    return dict(_status)


def start_watcher(roms_path: Path):
    """Start a background folder watcher. Safe to call multiple times."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        _status["error"] = "watchdog not installed"
        logger.warning("watchdog not installed — folder watcher disabled")
        return

    from .scanner import scan_directory, CONSOLE_EXTENSIONS

    all_extensions = {ext for exts in CONSOLE_EXTENSIONS.values() for ext in exts}

    class RomHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in all_extensions:
                return
            _status["last_event"] = path.name
            _status["last_event_at"] = datetime.now().isoformat()
            _status["events_count"] = _status.get("events_count", 0) + 1
            logger.info(f"New ROM detected: {path}")
            try:
                result = scan_directory(roms_path)
                logger.info(f"Auto-scan result: {result}")
            except Exception as e:
                logger.error(f"Auto-scan error: {e}")

    try:
        observer = Observer()
        observer.schedule(RomHandler(), str(roms_path), recursive=True)
        observer.daemon = True
        observer.start()
        _status["active"] = True
        _status["path"] = str(roms_path)
        logger.info(f"Folder watcher started: {roms_path}")
    except Exception as e:
        _status["error"] = str(e)
        logger.error(f"Failed to start watcher: {e}")
