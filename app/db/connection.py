"""app.db.connection - SQLite schema initialization, table migrations, and tag tables."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    AestheticTags,
)


def ensure_tag_tables(connection: sqlite3.Connection) -> None:
    """Create the controlled tag catalog and normalized per-analysis tag table."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS photo_tag_catalog (
            category_key TEXT NOT NULL,
            category_label TEXT NOT NULL,
            tag TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            PRIMARY KEY (category_key, tag)
        )"""
    )
    catalog_rows = [
        (category_key, AESTHETIC_TAG_CATEGORIES[category_key], tag, order)
        for category_key, options in AESTHETIC_TAG_OPTIONS.items()
        for order, tag in enumerate(options)
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO photo_tag_catalog "
        "(category_key, category_label, tag, sort_order) VALUES (?, ?, ?, ?)",
        catalog_rows,
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS photo_analysis_tags (
            analysis_id INTEGER NOT NULL REFERENCES photo_analyses(id) ON DELETE CASCADE,
            category_key TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (analysis_id, category_key, tag),
            FOREIGN KEY (category_key, tag)
                REFERENCES photo_tag_catalog(category_key, tag)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_photo_analysis_tags_category_tag "
        "ON photo_analysis_tags (category_key, tag)"
    )


def sync_analysis_tags(
    connection: sqlite3.Connection,
    analysis_id: int,
    tags: AestheticTags,
) -> None:
    """Replace the normalized tag rows for one analysis."""
    connection.execute(
        "DELETE FROM photo_analysis_tags WHERE analysis_id = ?",
        (analysis_id,),
    )
    connection.executemany(
        "INSERT INTO photo_analysis_tags (analysis_id, category_key, tag) VALUES (?, ?, ?)",
        [
            (analysis_id, category_key, tag)
            for category_key, values in tags.model_dump(mode="python").items()
            for tag in values
        ],
    )


def get_db_connection(db_path: Path | str, timeout: float = 30.0) -> sqlite3.Connection:
    """Return a configured SQLite connection with WAL mode, busy timeout, and foreign keys."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.OperationalError:
        pass
    return conn


_ENSURED_DBS: dict[str, float] = {}


def ensure_db_columns(db_path: Path | str) -> None:
    """Ensure all required columns and tables exist in the SQLite database (cached per file mtime)."""
    database = Path(db_path).expanduser()
    if not database.is_file():
        return
    try:
        resolved_str = str(database.resolve())
        mtime = database.stat().st_mtime
    except OSError:
        return
    if _ENSURED_DBS.get(resolved_str) == mtime:
        return

    with closing(get_db_connection(database)) as conn, conn:
        ensure_tag_tables(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(photo_analyses)").fetchall()]
        if not cols:
            return
        if "thumbnail" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN thumbnail BLOB")
        if "lr_advice_json" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN lr_advice_json TEXT")
        if "sns_advice_json" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN sns_advice_json TEXT")
        if "review_status" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN review_status TEXT DEFAULT '미검토'")
        if "user_notes" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN user_notes TEXT DEFAULT ''")
        if "dhash" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN dhash INTEGER")
        if "user_score" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN user_score REAL")

        missing = conn.execute(
            "SELECT id, thumbnail FROM photo_analyses WHERE dhash IS NULL AND thumbnail IS NOT NULL"
        ).fetchall()
        if missing:
            from app.services.image_processor import compute_dhash_from_bytes, dhash_to_sqlite
            for mid, mthumb in missing:
                try:
                    dh = compute_dhash_from_bytes(mthumb)
                    conn.execute("UPDATE photo_analyses SET dhash = ? WHERE id = ?", (dhash_to_sqlite(dh), mid))
                except Exception:
                    pass
    try:
        _ENSURED_DBS[resolved_str] = database.stat().st_mtime
    except OSError:
        pass
