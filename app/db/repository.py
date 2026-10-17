"""app.db.repository - CRUD and query methods for photo analyses."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.connection import (
    ensure_db_columns,
    ensure_tag_tables,
    get_db_connection,
    sync_analysis_tags,
)
from app.models.analysis import AESTHETIC_TAG_CATEGORIES, CrossCheckOpinion, PhotoAnalysis, get_score_grade
from app.services.image_processor import (
    PreparedPhoto,
    compute_dhash_from_bytes,
    dhash_from_sqlite,
    dhash_to_sqlite,
    get_original_photo_path,
    save_original_photo,
    _json_safe,
)


def save_analysis(
    db_path: str | Path,
    photo: PreparedPhoto,
    model: str,
    analysis: PhotoAnalysis,
    thumbnail: bytes | None = None,
) -> int:
    """Persist the privacy-filtered EXIF and validated analysis JSON in SQLite, with lightweight thumbnail."""
    database = Path(db_path).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    thumb_data = thumbnail if thumbnail is not None else getattr(photo, "thumbnail_bytes", None)
    with closing(get_db_connection(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS photo_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                image_format TEXT NOT NULL,
                model TEXT NOT NULL,
                exif_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                thumbnail BLOB
            )"""
        )
        existing_cols = [r[1] for r in connection.execute("PRAGMA table_info(photo_analyses)").fetchall()]
        for col_name, col_type in (
            ("thumbnail", "BLOB"),
            ("lr_advice_json", "TEXT"),
            ("sns_advice_json", "TEXT"),
            ("dhash", "INTEGER"),
            ("user_score", "REAL"),
                ("captured_at", "TEXT"),
        ):
            if col_name not in existing_cols:
                try:
                    connection.execute(f"ALTER TABLE photo_analyses ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass
        ensure_tag_tables(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_photo_analyses_sha256 "
            "ON photo_analyses (sha256)"
        )
        dhash_to_save = getattr(photo, "dhash", None)
        if dhash_to_save is None and thumb_data:
            try:
                dhash_to_save = compute_dhash_from_bytes(thumb_data)
            except Exception:
                dhash_to_save = None

        cursor = connection.execute(
            """INSERT INTO photo_analyses (
                sha256, source_filename, width, height, image_format,
                model, exif_json, analysis_json, created_at, thumbnail, dhash, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                photo.sha256,
                photo.source_filename,
                photo.width,
                photo.height,
                photo.image_format,
                model,
                json.dumps(photo.safe_exif, ensure_ascii=False, sort_keys=True),
                analysis.model_dump_json(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                thumb_data,
                dhash_to_sqlite(dhash_to_save),
                photo.captured_at,
            ),
        )
        record_id = int(cursor.lastrowid)
        sync_analysis_tags(connection, record_id, analysis.aesthetic_tags)
        save_original_photo(database, photo)
        return record_id


def find_existing_analysis(db_path: Path, sha256: str, model: str | None = None) -> tuple[int, dict] | None:
    """Return (record_id, analysis dict) of the latest stored analysis with the same file hash and optional model."""
    if not db_path.is_file():
        return None
    with closing(get_db_connection(db_path)) as conn:
        try:
            if model:
                row = conn.execute(
                    "SELECT id, analysis_json FROM photo_analyses WHERE sha256 = ? AND model = ? ORDER BY id DESC LIMIT 1",
                    (sha256, model),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id, analysis_json FROM photo_analyses WHERE sha256 = ? ORDER BY id DESC LIMIT 1",
                    (sha256,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
    if not row:
        return None
    try:
        return int(row[0]), json.loads(row[1])
    except (TypeError, ValueError):
        return None


def get_all_analyses(db_path: Path, max_hamming_dist: int = 15) -> list[dict]:
    """Retrieve all photo analysis records with tags and group into burst clusters."""
    if not db_path.is_file():
        return []
    ensure_db_columns(db_path)
    with closing(get_db_connection(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, sha256, source_filename, width, height, image_format,
                      model, exif_json, analysis_json, created_at,
                      lr_advice_json, sns_advice_json, review_status,
                      user_notes, dhash, user_score, captured_at
               FROM photo_analyses ORDER BY id DESC"""
        ).fetchall()

        tag_rows = conn.execute(
            "SELECT analysis_id, category_key, tag FROM photo_analysis_tags"
        ).fetchall()

        tags_by_id: dict[int, dict[str, list[str]]] = {}
        for r in tag_rows:
            aid = int(r["analysis_id"])
            ckey = str(r["category_key"])
            tag = str(r["tag"])
            tags_by_id.setdefault(aid, {}).setdefault(ckey, []).append(tag)

        missing_dhash_ids = [int(r["id"]) for r in rows if r["dhash"] is None]
        dhash_overrides: dict[int, int] = {}
        if missing_dhash_ids:
            thumb_rows = []
            for idx in range(0, len(missing_dhash_ids), 500):
                chunk = missing_dhash_ids[idx : idx + 500]
                placeholders = ",".join("?" for _ in chunk)
                thumb_rows.extend(
                    conn.execute(
                        f"SELECT id, thumbnail FROM photo_analyses WHERE id IN ({placeholders}) AND thumbnail IS NOT NULL",
                        chunk,
                    ).fetchall()
                )
            with conn:
                for tr in thumb_rows:
                    tid = int(tr[0])
                    tbytes = tr[1]
                    if tbytes:
                        try:
                            dh = compute_dhash_from_bytes(tbytes)
                            dhash_overrides[tid] = dh
                            conn.execute("UPDATE photo_analyses SET dhash = ? WHERE id = ?", (dhash_to_sqlite(dh), tid))
                        except Exception:
                            pass

    results = []
    for row in rows:
        aid = int(row["id"])
        formatted = _format_analysis_row(
            row,
            tags_by_id.get(aid),
            dhash_override=dhash_overrides.get(aid),
        )
        if formatted:
            results.append(formatted)
    from app.services.burst_detector import cluster_burst_groups
    return cluster_burst_groups(results, max_hamming_dist=max_hamming_dist)


def _format_analysis_row(
    row: sqlite3.Row | dict[str, Any],
    tags_dict: dict[str, list[str]] | None = None,
    dhash_override: int | None = None,
) -> dict[str, Any] | None:
    """Format a raw database row into the standardized analysis record dictionary."""
    aid = int(row["id"])
    try:
        analysis_data = json.loads(row["analysis_json"])
        exif_data = _json_safe(json.loads(row["exif_json"]))
    except Exception:
        return None

    lr_advice = None
    if "lr_advice_json" in row.keys() and row["lr_advice_json"]:
        try:
            lr_advice = json.loads(row["lr_advice_json"])
        except Exception:
            pass

    sns_advice = None
    if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
        try:
            sns_advice = json.loads(row["sns_advice_json"])
        except Exception:
            pass

    dhash_val = row["dhash"] if "dhash" in row.keys() and row["dhash"] is not None else None
    if dhash_val is not None:
        dhash_val = dhash_from_sqlite(dhash_val)
    elif dhash_override is not None:
        dhash_val = dhash_override
    elif "thumbnail" in row.keys() and row["thumbnail"]:
        try:
            dhash_val = compute_dhash_from_bytes(row["thumbnail"])
        except Exception:
            dhash_val = None

    final_score = float(analysis_data.get("final_score", 0))
    tags = tags_dict if tags_dict is not None else analysis_data.get("aesthetic_tags", {})
    return {
        "id": aid,
        "sha256": row["sha256"],
        "filename": row["source_filename"],
        "width": row["width"],
        "height": row["height"],
        "format": row["image_format"],
        "model": row["model"],
        "created_at": row["created_at"],
        "captured_at": row["captured_at"] if "captured_at" in row.keys() else None,
        "review_status": row["review_status"] if "review_status" in row.keys() else "미검토",
        "user_notes": row["user_notes"] if "user_notes" in row.keys() else "",
        "user_score": float(row["user_score"]) if "user_score" in row.keys() and row["user_score"] is not None else None,
        "final_score": final_score,
        "grade": get_score_grade(final_score),
        "figure_category": analysis_data.get("figure_category", "일반 피규어 촬영"),
        "focus_status": analysis_data.get("focus_status", "완벽 칼초점"),
        "focus_notes": analysis_data.get("focus_notes", ""),
        "composition_score": float(analysis_data.get("composition_score", 0)),
        "composition_notes": analysis_data.get("composition_notes", ""),
        "lighting_score": float(analysis_data.get("lighting_score", 0)),
        "lighting_notes": analysis_data.get("lighting_notes", ""),
        "color_score": float(analysis_data.get("color_score", 0)),
        "color_notes": analysis_data.get("color_notes", ""),
        "technique_score": float(analysis_data.get("technique_score", 0)),
        "technique_notes": analysis_data.get("technique_notes", ""),
        "final_reason": analysis_data.get("final_reason", ""),
        "strengths": analysis_data.get("strengths", []),
        "improvements": analysis_data.get("improvements", []),
        "aesthetic_tags": tags,
        "detected_camera_settings": analysis_data.get("detected_camera_settings"),
        "cross_check_opinion": analysis_data.get("cross_check_opinion"),
        "lr_advice": lr_advice,
        "sns_advice": sns_advice,
        "exif": exif_data,
        "dhash": dhash_val,
    }


def get_analysis_by_id(db_path: Path, record_id: int) -> dict[str, Any] | None:
    """Retrieve a single fully-formatted analysis record by ID with aesthetic tags."""
    if not db_path.is_file():
        return None
    ensure_db_columns(db_path)
    with closing(get_db_connection(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
        if not row:
            return None
        tag_rows = conn.execute(
            "SELECT category_key, tag FROM photo_analysis_tags WHERE analysis_id = ?",
            (record_id,),
        ).fetchall()

    tags_dict: dict[str, list[str]] = {}
    for r in tag_rows:
        ckey = str(r["category_key"])
        tag = str(r["tag"])
        tags_dict.setdefault(ckey, []).append(tag)

    return _format_analysis_row(row, tags_dict)


def update_analysis(
    db_path: str | Path,
    record_id: int,
    model: str,
    analysis: PhotoAnalysis,
) -> dict[str, Any] | None:
    """Update model and complete analysis JSON for an existing record, re-syncing tags."""
    database = Path(db_path).expanduser()
    ensure_db_columns(database)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(get_db_connection(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "UPDATE photo_analyses SET model = ?, analysis_json = ?, created_at = ? WHERE id = ?",
            (model, analysis.model_dump_json(), now_iso, record_id),
        )
        sync_analysis_tags(connection, record_id, analysis.aesthetic_tags)
    return get_analysis_by_id(database, record_id)


def update_cross_check_opinion(
    db_path: str | Path,
    record_id: int,
    cross_check: CrossCheckOpinion,
) -> dict[str, Any] | None:
    """Update only the cross_check_opinion inside analysis_json without modifying base evaluation."""
    database = Path(db_path).expanduser()
    ensure_db_columns(database)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(get_db_connection(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute(
            "SELECT analysis_json FROM photo_analyses WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
        except Exception:
            data = {}
        data["cross_check_opinion"] = cross_check.model_dump()
        connection.execute(
            "UPDATE photo_analyses SET analysis_json = ?, created_at = ? WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), now_iso, record_id),
        )
    return get_analysis_by_id(database, record_id)



def get_tag_stats(db_path: Path, min_count: int = 1) -> dict:
    """Aggregate statistics by aesthetic tag, including AI scores and user ratings."""
    ensure_db_columns(db_path)
    analyses = get_all_analyses(db_path)

    total_photos = len(analyses)
    user_rated_photos = sum(1 for a in analyses if a.get("user_score") is not None)

    tag_data: dict[tuple[str, str], dict] = {}

    for a in analyses:
        tags_dict = a.get("aesthetic_tags") or {}
        ai_score = float(a.get("final_score") or 0.0)
        u_score = a.get("user_score")
        light_score = float(a.get("lighting_score") or 0.0)
        comp_score = float(a.get("composition_score") or 0.0)
        tech_score = float(a.get("technique_score") or 0.0)
        color_score = float(a.get("color_score") or 0.0)

        for cat_key, t_list in tags_dict.items():
            if not isinstance(t_list, list):
                continue
            cat_name = AESTHETIC_TAG_CATEGORIES.get(cat_key, cat_key)
            for t in t_list:
                key = (cat_key, t)
                if key not in tag_data:
                    tag_data[key] = {
                        "category_key": cat_key,
                        "category_name": cat_name,
                        "tag": t,
                        "count": 0,
                        "ai_scores": [],
                        "user_scores": [],
                        "lighting_scores": [],
                        "composition_scores": [],
                        "technique_scores": [],
                        "color_scores": [],
                    }
                td = tag_data[key]
                td["count"] += 1
                td["ai_scores"].append(ai_score)
                if u_score is not None:
                    td["user_scores"].append(float(u_score))
                td["lighting_scores"].append(light_score)
                td["composition_scores"].append(comp_score)
                td["technique_scores"].append(tech_score)
                td["color_scores"].append(color_score)

    items = []
    for (cat_key, t), td in tag_data.items():
        if td["count"] < min_count:
            continue
        avg_ai = sum(td["ai_scores"]) / len(td["ai_scores"]) if td["ai_scores"] else 0.0
        avg_user = (sum(td["user_scores"]) / len(td["user_scores"])) if td["user_scores"] else None
        avg_light = sum(td["lighting_scores"]) / len(td["lighting_scores"]) if td["lighting_scores"] else 0.0
        avg_comp = sum(td["composition_scores"]) / len(td["composition_scores"]) if td["composition_scores"] else 0.0
        avg_tech = sum(td["technique_scores"]) / len(td["technique_scores"]) if td["technique_scores"] else 0.0
        avg_color = sum(td["color_scores"]) / len(td["color_scores"]) if td["color_scores"] else 0.0

        score_diff = round(avg_user - avg_ai, 2) if avg_user is not None else None

        items.append({
            "category_key": cat_key,
            "category_name": td["category_name"],
            "tag": t,
            "count": td["count"],
            "avg_ai_score": round(avg_ai, 2),
            "avg_user_score": round(avg_user, 2) if avg_user is not None else None,
            "score_diff": score_diff,
            "user_rated_count": len(td["user_scores"]),
            "avg_lighting_score": round(avg_light, 2),
            "avg_composition_score": round(avg_comp, 2),
            "avg_technique_score": round(avg_tech, 2),
            "avg_color_score": round(avg_color, 2),
        })

    items.sort(key=lambda x: x["avg_ai_score"], reverse=True)

    top_ai_tags = items[:5]
    bottom_ai_tags = sorted(items, key=lambda x: x["avg_ai_score"])[:5] if len(items) >= 2 else []

    with_user = [x for x in items if x["avg_user_score"] is not None]
    top_user_fav_tags = sorted(with_user, key=lambda x: (x["score_diff"] or 0), reverse=True)[:5]

    categories_dict: dict[str, list] = {}
    for it in items:
        categories_dict.setdefault(it["category_key"], []).append(it)

    return {
        "total_photos": total_photos,
        "user_rated_photos": user_rated_photos,
        "total_unique_tags": len(tag_data),
        "filtered_tags_count": len(items),
        "min_count": min_count,
        "all_tags": items,
        "top_ai_tags": top_ai_tags,
        "bottom_ai_tags": bottom_ai_tags,
        "top_user_fav_tags": top_user_fav_tags,
        "categories": categories_dict,
        "category_names": AESTHETIC_TAG_CATEGORIES,
    }


def get_photo_thumbnail_and_hash(db_path: Path, record_id: int) -> tuple[bytes | None, str, str] | None:
    """Retrieve thumbnail blob, source filename, and SHA256 hash for a specific record."""
    if not db_path.is_file():
        return None
    with closing(get_db_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT thumbnail, source_filename, sha256 FROM photo_analyses WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return None
        return (row[0], row[1], row[2])


def update_photo_thumbnail(db_path: Path, record_id: int, thumb_bytes: bytes) -> None:
    """Update cached thumbnail blob for an analysis record."""
    with closing(get_db_connection(db_path)) as conn, conn:
        conn.execute("UPDATE photo_analyses SET thumbnail = ? WHERE id = ?", (thumb_bytes, record_id))


def update_review_status(db_path: Path, record_id: int, new_status: str) -> bool:
    """Update review_status for a record."""
    ensure_db_columns(db_path)
    with closing(get_db_connection(db_path)) as conn, conn:
        cursor = conn.execute("UPDATE photo_analyses SET review_status = ? WHERE id = ?", (new_status, record_id))
        return cursor.rowcount > 0


def update_user_score(db_path: Path, record_id: int, user_score: float | None) -> bool:
    """Update user rating score for a record."""
    ensure_db_columns(db_path)
    with closing(get_db_connection(db_path)) as conn, conn:
        cursor = conn.execute("UPDATE photo_analyses SET user_score = ? WHERE id = ?", (user_score, record_id))
        return cursor.rowcount > 0


def delete_analyses(db_path: Path, record_ids: list[int]) -> list[int]:
    """Delete analysis records, associated tag mappings, and unreferenced original photo files."""
    if not record_ids:
        return []
    ensure_db_columns(db_path)
    with closing(get_db_connection(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        rows = []
        for idx in range(0, len(record_ids), 500):
            chunk = record_ids[idx : idx + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    f"SELECT id, sha256 FROM photo_analyses WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
            conn.execute(f"DELETE FROM photo_analysis_tags WHERE analysis_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM photo_analyses WHERE id IN ({placeholders})", chunk)
        remaining_hashes = {
            row[0]
            for row in conn.execute("SELECT sha256 FROM photo_analyses").fetchall()
        }
        for row in rows:
            if row[1] in remaining_hashes:
                continue
            for mime_type in ("image/jpeg", "image/png", "image/webp"):
                original_path = get_original_photo_path(db_path, row[1], mime_type)
                try:
                    original_path.unlink(missing_ok=True)
                except OSError:
                    pass
    existing_ids = {row[0] for row in rows}
    return [record_id for record_id in record_ids if record_id in existing_ids]


def get_analysis_row_by_id(db_path: Path | str, record_id: int) -> dict[str, Any] | None:
    """Retrieve raw analysis database row by record ID."""
    database = Path(db_path)
    if not database.is_file():
        return None
    ensure_db_columns(database)
    with closing(get_db_connection(database)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None


def update_lr_advice(db_path: Path, record_id: int, lr_advice_json: str) -> None:
    """Persist generated Lightroom post-processing advice JSON to the record."""
    with closing(get_db_connection(db_path)) as conn, conn:
        conn.execute("UPDATE photo_analyses SET lr_advice_json = ? WHERE id = ?", (lr_advice_json, record_id))


def update_sns_advice(db_path: Path, record_id: int, sns_advice_json: str) -> None:
    """Persist generated SNS crop & caption advice JSON to the record."""
    with closing(get_db_connection(db_path)) as conn, conn:
        conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (sns_advice_json, record_id))


def get_analyses_and_tags_for_export(db_path: Path) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    """Retrieve all rows and associated tags for bulk export operations (e.g., XMP sidecars)."""
    if not db_path.is_file():
        return [], {}
    with closing(get_db_connection(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM photo_analyses").fetchall()]
        tag_rows = conn.execute("SELECT analysis_id, tag FROM photo_analysis_tags").fetchall()
    tags_by_id: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_by_id.setdefault(int(r["analysis_id"]), []).append(str(r["tag"]))
    return rows, tags_by_id
