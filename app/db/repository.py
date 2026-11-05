"""app.db.repository - CRUD and query methods for photo analyses."""

from __future__ import annotations

import json
import re
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
    compute_color_sig_from_bytes,
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
            ("color_sig", "INTEGER"),
            ("is_excluded", "INTEGER DEFAULT 0"),
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

        color_sig_to_save = getattr(photo, "color_sig", None)
        if color_sig_to_save is None and thumb_data:
            try:
                color_sig_to_save = compute_color_sig_from_bytes(thumb_data)
            except Exception:
                color_sig_to_save = None

        cursor = connection.execute(
            """INSERT INTO photo_analyses (
                sha256, source_filename, width, height, image_format,
                model, exif_json, analysis_json, created_at, thumbnail, dhash, captured_at, color_sig
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                color_sig_to_save,
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
                      user_notes, dhash, user_score, captured_at, color_sig,
                      is_excluded
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

        collections_by_id: dict[int, list[int]] = {}
        try:
            col_rows = conn.execute(
                "SELECT analysis_id, collection_id FROM photo_collection_items ORDER BY collection_id ASC"
            ).fetchall()
            for cr in col_rows:
                collections_by_id.setdefault(int(cr["analysis_id"]), []).append(int(cr["collection_id"]))
        except sqlite3.OperationalError:
            pass

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
            collection_ids=collections_by_id.get(aid, []),
        )
        if formatted:
            results.append(formatted)
    from app.services.burst_detector import cluster_burst_groups
    return cluster_burst_groups(results, max_hamming_dist=max_hamming_dist)


FOCAL_BAND_DEFINITIONS: list[dict[str, Any]] = [
    {"key": "wide_24", "label": "24mm 이하 (광각)", "short_label": "24mm 광각", "order": 1, "min_mm": 0.0, "max_mm": 28.0},
    {"key": "semi_wide_35", "label": "35mm 부근 (준광각)", "short_label": "35mm 준광각", "order": 2, "min_mm": 28.0, "max_mm": 40.0},
    {"key": "standard_50", "label": "50mm 부근 (표준)", "short_label": "50mm 표준", "order": 3, "min_mm": 40.0, "max_mm": 60.0},
    {"key": "portrait_85", "label": "70~85mm (준망원)", "short_label": "70~85mm 준망원", "order": 4, "min_mm": 60.0, "max_mm": 90.0},
    {"key": "tele_100", "label": "100mm+ (망원/매크로)", "short_label": "100mm+ 망원/접사", "order": 5, "min_mm": 90.0, "max_mm": 9999.0},
    {"key": "unknown", "label": "미식별 (EXIF 없음)", "short_label": "화각 미식별", "order": 6, "min_mm": None, "max_mm": None},
]

STRENGTH_THEME_PATTERNS: list[tuple[str, list[str]]] = [
    ("🎯 칼초점 & 눈동자 디테일", ["초점", "눈동자", "선명", "데칼", "디테일", "명확"]),
    ("✨ 배경 분리 & 보케(심도)", ["분리", "흐림", "보케", "심도", "아웃포커싱"]),
    ("🎨 색감 대비 & 톤 조화", ["색", "톤", "파스텔", "화사", "대비", "조화"]),
    ("🌿 공간감 & 스토리텔링 연출", ["소품", "공간", "맥락", "상황", "분위기", "야외", "레이어", "배경"]),
    ("📐 안정적인 구도 & 프레이밍", ["구도", "프레이밍", "실루엣", "배치", "포즈", "시선"]),
    ("💡 자연스러운 빛 & 조명 활용", ["자연광", "조명", "광원", "빛", "역광"]),
]

IMPROVEMENT_THEME_PATTERNS: list[tuple[str, list[str]]] = [
    ("💡 입체감 부족 (림라이트·측광 필요)", ["림라이트", "사광", "측광", "측면", "입체감", "보조광"]),
    ("✂️ 가장자리 잘림 & 여백 답답함", ["여백", "잘림", "크롭", "답답", "가장자리", "하단", "머리 위"]),
    ("🧹 주변 산만함 & 시선 분산 요소", ["시선 분산", "산만", "정리", "덜어", "빈 벽", "배경의", "가리지", "프레임 밖"]),
    ("🔍 피사체 비중 부족 (더 크게 촬영 권장)", ["크게 담", "비중을 줄", "존재감", "주인공으로", "타이트하게"]),
    ("☀️ 반사 하이라이트 & 노출·대비 제어", ["반사", "하이라이트", "확산", "대비", "어두운", "노출", "밝기", "붉은 조명"]),
    ("🎯 초점·피사계심도 보완", ["초점", "흔들림", "심도", "조리개", "선명"]),
]


def _parse_numeric_mm(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        fval = float(val)
        return round(fval, 1) if 1.0 <= fval <= 2000.0 else None
    if isinstance(val, (list, tuple)) and len(val) == 2:
        try:
            den = float(val[1])
            if den != 0:
                fval = float(val[0]) / den
                return round(fval, 1) if 1.0 <= fval <= 2000.0 else None
        except (TypeError, ValueError):
            pass
    s = str(val).strip()
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        try:
            fval = float(m.group(1))
            return round(fval, 1) if 1.0 <= fval <= 2000.0 else None
        except ValueError:
            pass
    return None


def extract_focal_length_mm(
    exif_data: dict[str, Any] | None,
    detected_camera_settings: dict[str, Any] | None = None,
) -> float | None:
    """Extract focal length in mm prioritizing 35mm equivalent EXIF, actual EXIF, then AI OCR settings."""
    exif = exif_data if isinstance(exif_data, dict) else {}
    det = detected_camera_settings if isinstance(detected_camera_settings, dict) else {}

    # 1. EXIF FocalLengthIn35mmFilm (full-frame equivalent)
    for k in ("FocalLengthIn35mmFilm", "FocalLengthIn35mmFormat"):
        fl = _parse_numeric_mm(exif.get(k))
        if fl is not None:
            return fl

    # 2. EXIF FocalLength
    fl = _parse_numeric_mm(exif.get("FocalLength"))
    if fl is not None:
        return fl

    # 3. AI detected_camera_settings focal_length
    for k in ("focal_length", "FocalLength"):
        fl = _parse_numeric_mm(det.get(k))
        if fl is not None:
            return fl

    # 4. Single prime lens string in detected_camera_settings.lens or EXIF LensModel (exclude zoom ranges like 24-70mm)
    lens_str = str(det.get("lens") or exif.get("LensModel") or "").strip()
    if lens_str and not re.search(r"\d+\s*-\s*\d+\s*mm", lens_str, re.IGNORECASE):
        m_prime = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*mm\b", lens_str, re.IGNORECASE)
        if m_prime:
            try:
                fval = float(m_prime.group(1))
                if 8.0 <= fval <= 1200.0:
                    return round(fval, 1)
            except ValueError:
                pass

    return None


def extract_lens_model(
    exif_data: dict[str, Any] | None,
    detected_camera_settings: dict[str, Any] | None = None,
) -> str:
    """Extract human-readable lens model name from EXIF or detected camera settings."""
    exif = exif_data if isinstance(exif_data, dict) else {}
    det = detected_camera_settings if isinstance(detected_camera_settings, dict) else {}
    lens = str(exif.get("LensModel") or det.get("lens") or "").strip()
    return lens


def classify_focal_band(focal_mm: float | None) -> dict[str, Any]:
    """Classify a numeric focal length (mm) into one of the 5 standard photographic bands (or unknown)."""
    if focal_mm is None or focal_mm <= 0:
        return FOCAL_BAND_DEFINITIONS[-1]
    if focal_mm <= 28.0:
        return FOCAL_BAND_DEFINITIONS[0]
    if focal_mm <= 40.0:
        return FOCAL_BAND_DEFINITIONS[1]
    if focal_mm <= 60.0:
        return FOCAL_BAND_DEFINITIONS[2]
    if focal_mm <= 90.0:
        return FOCAL_BAND_DEFINITIONS[3]
    return FOCAL_BAND_DEFINITIONS[4]


def _format_analysis_row(
    row: sqlite3.Row | dict[str, Any],
    tags_dict: dict[str, list[str]] | None = None,
    dhash_override: int | None = None,
    collection_ids: list[int] | None = None,
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

    color_sig_val = int(row["color_sig"]) if "color_sig" in row.keys() and row["color_sig"] is not None else None
    if color_sig_val is None and "thumbnail" in row.keys() and row["thumbnail"]:
        try:
            color_sig_val = compute_color_sig_from_bytes(row["thumbnail"])
        except Exception:
            color_sig_val = None

    final_score = float(analysis_data.get("final_score", 0))
    tags = tags_dict if tags_dict is not None else analysis_data.get("aesthetic_tags", {})
    detected_settings = analysis_data.get("detected_camera_settings")
    focal_mm = extract_focal_length_mm(exif_data, detected_settings)
    focal_band = classify_focal_band(focal_mm)
    lens_model = extract_lens_model(exif_data, detected_settings)
    raw_analysis_mode = analysis_data.get("analysis_mode")
    if raw_analysis_mode in ("full", "fast"):
        analysis_mode = raw_analysis_mode
    else:
        has_notes = any(
            bool(str(analysis_data.get(k, "")).strip())
            for k in ("composition_notes", "lighting_notes", "color_notes", "technique_notes")
        )
        has_lists = bool(analysis_data.get("strengths")) or bool(analysis_data.get("improvements"))
        analysis_mode = "full" if (has_notes or has_lists) else "fast"

    return {
        "id": aid,
        "sha256": row["sha256"],
        "filename": row["source_filename"],
        "width": row["width"],
        "height": row["height"],
        "format": row["image_format"],
        "model": row["model"],
        "analysis_mode": analysis_mode,
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
        "detected_camera_settings": detected_settings,
        "focal_length_mm": focal_mm,
        "focal_band_key": focal_band["key"],
        "focal_band_label": focal_band["label"],
        "focal_band_short": focal_band["short_label"],
        "lens_model": lens_model,
        "cross_check_opinion": analysis_data.get("cross_check_opinion"),
        "lr_advice": lr_advice,
        "sns_advice": sns_advice,
        "exif": exif_data,
        "dhash": dhash_val,
        "color_sig": color_sig_val,
        "is_excluded": bool(row["is_excluded"]) if "is_excluded" in row.keys() and row["is_excluded"] is not None else False,
        "collection_ids": list(collection_ids) if collection_ids is not None else [],
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
        try:
            col_rows = conn.execute(
                "SELECT collection_id FROM photo_collection_items WHERE analysis_id = ? ORDER BY collection_id ASC",
                (record_id,),
            ).fetchall()
            collection_ids = [int(r["collection_id"]) for r in col_rows]
        except sqlite3.OperationalError:
            collection_ids = []

    tags_dict: dict[str, list[str]] = {}
    for r in tag_rows:
        ckey = str(r["category_key"])
        tag = str(r["tag"])
        tags_dict.setdefault(ckey, []).append(tag)

    return _format_analysis_row(row, tags_dict, collection_ids=collection_ids)


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


def _iso_to_local_date_str(iso_str: str | None) -> str | None:
    """Convert an ISO timestamp string into a local YYYY-MM-DD date string."""
    if not iso_str:
        return None
    s = str(iso_str).strip()
    if not s:
        return None
    # Naive ISO date/datetime (like EXIF DateTimeOriginal '2026-11-01T14:23:05') is already camera local time
    if len(s) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", s):
        tail = s[10:]
        if not re.search(r"(Z|[+-]\d{2}:?\d{2})$", tail):
            return s[:10]
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return s[:10] if len(s) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", s) else None


def extract_item_date_str(
    item: dict[str, Any],
    date_basis: str = "smart",
) -> str | None:
    """Return YYYY-MM-DD date string for an analysis item based on date_basis ('smart'|'captured'|'created')."""
    basis = (date_basis or "smart").strip().lower()
    cap_date = _iso_to_local_date_str(item.get("captured_at"))
    cre_date = _iso_to_local_date_str(item.get("created_at"))
    if basis == "captured":
        return cap_date
    if basis == "created":
        return cre_date
    return cap_date or cre_date


def filter_analyses_by_date(
    analyses: list[dict[str, Any]],
    date_basis: str = "smart",
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """Filter analysis items by date range (inclusive YYYY-MM-DD) or missing capture date."""
    basis = (date_basis or "smart").strip().lower()
    d_from = (date_from or "").strip() or None
    d_to = (date_to or "").strip() or None

    if basis == "captured_missing":
        return [a for a in analyses if not _iso_to_local_date_str(a.get("captured_at"))]

    if not d_from and not d_to and basis != "captured_only":
        return analyses

    filtered: list[dict[str, Any]] = []
    for a in analyses:
        d_str = extract_item_date_str(a, "captured" if basis == "captured_only" else basis)
        if not d_str:
            continue
        if d_from and d_str < d_from:
            continue
        if d_to and d_str > d_to:
            continue
        filtered.append(a)
    return filtered


def filter_analyses_by_collection(
    analyses: list[dict[str, Any]],
    collection_id: int | str | None = None,
) -> list[dict[str, Any]]:
    """Filter analysis items by collection_id ('all'/None, 'unassigned', or integer collection ID)."""
    if collection_id is None:
        return analyses
    s = str(collection_id).strip().lower()
    if not s or s == "all":
        return analyses
    if s in ("unassigned", "uncollected"):
        return [a for a in analyses if not a.get("collection_ids")]
    try:
        cid = int(s)
    except ValueError:
        return analyses
    return [a for a in analyses if cid in (a.get("collection_ids") or [])]


def get_tag_stats(
    db_path: Path,
    min_count: int = 1,
    date_basis: str = "smart",
    date_from: str | None = None,
    date_to: str | None = None,
    collection_id: int | str | None = None,
) -> dict:
    """Aggregate statistics by aesthetic tag, including AI scores and user ratings, optionally scoped by date and collection."""
    ensure_db_columns(db_path)
    all_analyses = get_all_analyses(db_path)
    analyses = filter_analyses_by_collection(all_analyses, collection_id=collection_id)
    analyses = filter_analyses_by_date(analyses, date_basis=date_basis, date_from=date_from, date_to=date_to)

    raw_total_photos = len(analyses)
    excluded_photos = sum(1 for a in analyses if a.get("is_excluded"))
    analyses = [a for a in analyses if not a.get("is_excluded")]

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
            if isinstance(t_list, str):
                t_list = [t_list.strip()] if t_list.strip() else []
            elif not isinstance(t_list, list):
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
        "excluded_photos": excluded_photos,
        "raw_total_photos": raw_total_photos,
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


def _summarize_feedback_themes(
    photo_texts_list: list[list[str]],
    theme_patterns: list[tuple[str, list[str]]],
    total_count: int,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Summarize per-photo strength/improvement lists into ranked photographic themes with sample quotes."""
    if total_count <= 0:
        return []
    results: list[dict[str, Any]] = []
    for theme_label, keywords in theme_patterns:
        matched_photos = 0
        sample_quote = ""
        for texts in photo_texts_list:
            if not isinstance(texts, list):
                continue
            hit = False
            for sentence in texts:
                s_str = str(sentence).strip()
                if any(kw in s_str for kw in keywords):
                    hit = True
                    if not sample_quote:
                        sample_quote = s_str
                    break
            if hit:
                matched_photos += 1
        if matched_photos > 0:
            results.append({
                "theme": theme_label,
                "photo_count": matched_photos,
                "pct": round((matched_photos / total_count) * 100),
                "sample": sample_quote,
            })
    results.sort(key=lambda x: x["photo_count"], reverse=True)
    return results[:top_n]


def get_focal_stats(
    db_path: Path,
    min_count: int = 1,
    date_basis: str = "smart",
    date_from: str | None = None,
    date_to: str | None = None,
    collection_id: int | str | None = None,
) -> dict[str, Any]:
    """Aggregate statistics, strengths, and weaknesses by focal length band and exact mm, optionally scoped by date and collection."""
    ensure_db_columns(db_path)
    all_analyses = get_all_analyses(db_path)
    analyses = filter_analyses_by_collection(all_analyses, collection_id=collection_id)
    analyses = filter_analyses_by_date(analyses, date_basis=date_basis, date_from=date_from, date_to=date_to)

    raw_total_photos = len(analyses)
    excluded_photos = sum(1 for a in analyses if a.get("is_excluded"))
    analyses = [a for a in analyses if not a.get("is_excluded")]

    total_photos = len(analyses)
    identified_photos = sum(1 for a in analyses if a.get("focal_length_mm") is not None)
    unknown_photos = total_photos - identified_photos
    user_rated_photos = sum(1 for a in analyses if a.get("user_score") is not None)

    band_buckets: dict[str, dict[str, Any]] = {}
    exact_buckets: dict[int, dict[str, Any]] = {}

    for bdef in FOCAL_BAND_DEFINITIONS:
        band_buckets[bdef["key"]] = {
            "def": bdef,
            "count": 0,
            "ai_scores": [],
            "user_scores": [],
            "lighting_scores": [],
            "composition_scores": [],
            "technique_scores": [],
            "color_scores": [],
            "photo_strengths": [],
            "photo_improvements": [],
            "tag_counts": {},
            "lens_counts": {},
            "exact_mm_scores": {},
        }

    for a in analyses:
        fl = a.get("focal_length_mm")
        bdef = classify_focal_band(fl)
        bkey = bdef["key"]
        bucket = band_buckets[bkey]

        ai_score = float(a.get("final_score") or 0.0)
        u_score = a.get("user_score")
        light_score = float(a.get("lighting_score") or 0.0)
        comp_score = float(a.get("composition_score") or 0.0)
        tech_score = float(a.get("technique_score") or 0.0)
        color_score = float(a.get("color_score") or 0.0)

        bucket["count"] += 1
        bucket["ai_scores"].append(ai_score)
        if u_score is not None:
            bucket["user_scores"].append(float(u_score))
        bucket["lighting_scores"].append(light_score)
        bucket["composition_scores"].append(comp_score)
        bucket["technique_scores"].append(tech_score)
        bucket["color_scores"].append(color_score)
        bucket["photo_strengths"].append(a.get("strengths") or [])
        bucket["photo_improvements"].append(a.get("improvements") or [])

        tags_dict = a.get("aesthetic_tags") or {}
        if isinstance(tags_dict, dict):
            for t_list in tags_dict.values():
                if isinstance(t_list, str):
                    t = t_list.strip()
                    if t:
                        bucket["tag_counts"][t] = bucket["tag_counts"].get(t, 0) + 1
                elif isinstance(t_list, list):
                    for t in t_list:
                        if t:
                            bucket["tag_counts"][t] = bucket["tag_counts"].get(t, 0) + 1

        lens = str(a.get("lens_model") or "").strip()
        if lens:
            bucket["lens_counts"][lens] = bucket["lens_counts"].get(lens, 0) + 1

        if fl is not None:
            mm_int = int(round(float(fl)))
            bucket["exact_mm_scores"].setdefault(mm_int, []).append(ai_score)
            if mm_int not in exact_buckets:
                exact_buckets[mm_int] = {
                    "mm": mm_int,
                    "label": f"{mm_int}mm",
                    "band_key": bkey,
                    "band_label": bdef["label"],
                    "count": 0,
                    "ai_scores": [],
                    "user_scores": [],
                    "lighting_scores": [],
                    "composition_scores": [],
                    "technique_scores": [],
                    "color_scores": [],
                    "photo_strengths": [],
                    "photo_improvements": [],
                }
            eb = exact_buckets[mm_int]
            eb["count"] += 1
            eb["ai_scores"].append(ai_score)
            if u_score is not None:
                eb["user_scores"].append(float(u_score))
            eb["lighting_scores"].append(light_score)
            eb["composition_scores"].append(comp_score)
            eb["technique_scores"].append(tech_score)
            eb["color_scores"].append(color_score)
            eb["photo_strengths"].append(a.get("strengths") or [])
            eb["photo_improvements"].append(a.get("improvements") or [])

    bands_result: list[dict[str, Any]] = []
    for bdef in FOCAL_BAND_DEFINITIONS:
        bkey = bdef["key"]
        bk = band_buckets[bkey]
        cnt = bk["count"]
        if cnt == 0:
            continue
        if bkey != "unknown" and cnt < min_count:
            continue

        avg_ai = sum(bk["ai_scores"]) / cnt
        avg_user = (sum(bk["user_scores"]) / len(bk["user_scores"])) if bk["user_scores"] else None
        avg_light = sum(bk["lighting_scores"]) / cnt
        avg_comp = sum(bk["composition_scores"]) / cnt
        avg_tech = sum(bk["technique_scores"]) / cnt
        avg_color = sum(bk["color_scores"]) / cnt
        score_diff = round(avg_user - avg_ai, 2) if avg_user is not None else None

        top_tags = [
            {"tag": t, "count": c}
            for t, c in sorted(bk["tag_counts"].items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        lenses = [
            {"lens": l, "count": c}
            for l, c in sorted(bk["lens_counts"].items(), key=lambda x: x[1], reverse=True)[:3]
        ]
        exact_mms = [
            {
                "mm": mm_val,
                "label": f"{mm_val}mm",
                "count": len(scores),
                "avg_ai_score": round(sum(scores) / len(scores), 2),
            }
            for mm_val, scores in sorted(bk["exact_mm_scores"].items(), key=lambda x: x[0])
        ]

        bands_result.append({
            "band_key": bkey,
            "band_label": bdef["label"],
            "short_label": bdef["short_label"],
            "order": bdef["order"],
            "count": cnt,
            "avg_ai_score": round(avg_ai, 2),
            "avg_user_score": round(avg_user, 2) if avg_user is not None else None,
            "score_diff": score_diff,
            "user_rated_count": len(bk["user_scores"]),
            "avg_lighting_score": round(avg_light, 2),
            "avg_composition_score": round(avg_comp, 2),
            "avg_technique_score": round(avg_tech, 2),
            "avg_color_score": round(avg_color, 2),
            "top_strengths": _summarize_feedback_themes(bk["photo_strengths"], STRENGTH_THEME_PATTERNS, cnt, top_n=3),
            "top_improvements": _summarize_feedback_themes(bk["photo_improvements"], IMPROVEMENT_THEME_PATTERNS, cnt, top_n=3),
            "top_tags": top_tags,
            "lenses": lenses,
            "exact_mms": exact_mms,
        })

    exact_result: list[dict[str, Any]] = []
    for mm_val, eb in sorted(exact_buckets.items(), key=lambda x: x[0]):
        cnt = eb["count"]
        if cnt < min_count:
            continue
        avg_ai = sum(eb["ai_scores"]) / cnt
        avg_user = (sum(eb["user_scores"]) / len(eb["user_scores"])) if eb["user_scores"] else None
        score_diff = round(avg_user - avg_ai, 2) if avg_user is not None else None
        exact_result.append({
            "mm": mm_val,
            "label": eb["label"],
            "band_key": eb["band_key"],
            "band_label": eb["band_label"],
            "count": cnt,
            "avg_ai_score": round(avg_ai, 2),
            "avg_user_score": round(avg_user, 2) if avg_user is not None else None,
            "score_diff": score_diff,
            "user_rated_count": len(eb["user_scores"]),
            "avg_lighting_score": round(sum(eb["lighting_scores"]) / cnt, 2),
            "avg_composition_score": round(sum(eb["composition_scores"]) / cnt, 2),
            "avg_technique_score": round(sum(eb["technique_scores"]) / cnt, 2),
            "avg_color_score": round(sum(eb["color_scores"]) / cnt, 2),
            "top_strengths": _summarize_feedback_themes(eb["photo_strengths"], STRENGTH_THEME_PATTERNS, cnt, top_n=2),
            "top_improvements": _summarize_feedback_themes(eb["photo_improvements"], IMPROVEMENT_THEME_PATTERNS, cnt, top_n=2),
        })

    known_bands = [b for b in bands_result if b["band_key"] != "unknown"]
    best_band = max(known_bands, key=lambda x: x["avg_ai_score"]) if known_bands else None
    most_used_band = max(known_bands, key=lambda x: x["count"]) if known_bands else None
    weakest_band = min(known_bands, key=lambda x: x["avg_ai_score"]) if len(known_bands) >= 2 else None

    return {
        "total_photos": total_photos,
        "excluded_photos": excluded_photos,
        "raw_total_photos": raw_total_photos,
        "identified_photos": identified_photos,
        "unknown_photos": unknown_photos,
        "user_rated_photos": user_rated_photos,
        "min_count": min_count,
        "bands": bands_result,
        "exact_focal_lengths": exact_result,
        "best_band": best_band,
        "most_used_band": most_used_band,
        "weakest_band": weakest_band,
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


def update_analysis_excluded(db_path: Path | str, record_id: int, is_excluded: bool) -> bool:
    """Update is_excluded flag (0 or 1) for a single record."""
    database = Path(db_path)
    ensure_db_columns(database)
    val = 1 if is_excluded else 0
    with closing(get_db_connection(database)) as conn, conn:
        cursor = conn.execute("UPDATE photo_analyses SET is_excluded = ? WHERE id = ?", (val, record_id))
        return cursor.rowcount > 0


def batch_update_excluded(db_path: Path | str, record_ids: list[int], is_excluded: bool) -> int:
    """Batch update is_excluded flag for multiple records."""
    database = Path(db_path)
    if not database.is_file() or not record_ids:
        return 0
    ensure_db_columns(database)
    val = 1 if is_excluded else 0
    with closing(get_db_connection(database)) as conn, conn:
        placeholders = ",".join("?" for _ in record_ids)
        cursor = conn.execute(f"UPDATE photo_analyses SET is_excluded = ? WHERE id IN ({placeholders})", [val, *record_ids])
        return cursor.rowcount


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
            try:
                conn.execute(f"DELETE FROM photo_collection_items WHERE analysis_id IN ({placeholders})", chunk)
            except sqlite3.OperationalError:
                pass
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


# --- Lightroom-style Virtual Collections CRUD (Phase 2) ---

def get_all_collections(db_path: Path | str) -> list[dict[str, Any]]:
    """Retrieve all virtual collections with their member analysis IDs and count."""
    database = Path(db_path).expanduser()
    if not database.is_file():
        return []
    ensure_db_columns(database)
    with closing(get_db_connection(database)) as conn:
        conn.row_factory = sqlite3.Row
        from app.db.connection import ensure_collection_tables
        ensure_collection_tables(conn)
        col_rows = conn.execute(
            "SELECT id, name, color, created_at FROM photo_collections ORDER BY id ASC"
        ).fetchall()
        item_rows = conn.execute(
            "SELECT collection_id, analysis_id FROM photo_collection_items ORDER BY analysis_id DESC"
        ).fetchall()

    items_by_col: dict[int, list[int]] = {}
    for ir in item_rows:
        items_by_col.setdefault(int(ir["collection_id"]), []).append(int(ir["analysis_id"]))

    result: list[dict[str, Any]] = []
    for r in col_rows:
        cid = int(r["id"])
        aids = items_by_col.get(cid, [])
        result.append({
            "id": cid,
            "name": str(r["name"]),
            "color": str(r["color"] or "#4f46e5"),
            "created_at": str(r["created_at"]),
            "count": len(aids),
            "analysis_ids": aids,
        })
    return result


def create_collection(
    db_path: Path | str,
    name: str,
    color: str = "#4f46e5",
) -> dict[str, Any]:
    """Create a new virtual collection (or return existing one if name matches case-insensitively)."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("컬렉션 이름을 입력해 주세요.")
    clean_color = (color or "#4f46e5").strip() or "#4f46e5"
    database = Path(db_path).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    ensure_db_columns(database)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(get_db_connection(database)) as conn, conn:
        conn.row_factory = sqlite3.Row
        from app.db.connection import ensure_collection_tables
        ensure_collection_tables(conn)
        existing = conn.execute(
            "SELECT id, name, color, created_at FROM photo_collections WHERE name = ? COLLATE NOCASE",
            (clean_name,),
        ).fetchone()
        if existing:
            cid = int(existing["id"])
            item_rows = conn.execute(
                "SELECT analysis_id FROM photo_collection_items WHERE collection_id = ? ORDER BY analysis_id DESC",
                (cid,),
            ).fetchall()
            aids = [int(ir[0]) for ir in item_rows]
            return {
                "id": cid,
                "name": str(existing["name"]),
                "color": str(existing["color"] or "#4f46e5"),
                "created_at": str(existing["created_at"]),
                "count": len(aids),
                "analysis_ids": aids,
                "existing": True,
            }
        cursor = conn.execute(
            "INSERT INTO photo_collections (name, color, created_at) VALUES (?, ?, ?)",
            (clean_name, clean_color, now_iso),
        )
        cid = int(cursor.lastrowid)
        return {
            "id": cid,
            "name": clean_name,
            "color": clean_color,
            "created_at": now_iso,
            "count": 0,
            "analysis_ids": [],
            "existing": False,
        }


def rename_collection(
    db_path: Path | str,
    collection_id: int,
    new_name: str,
    color: str | None = None,
) -> dict[str, Any] | None:
    """Rename an existing collection and optionally update its color."""
    clean_name = (new_name or "").strip()
    if not clean_name:
        raise ValueError("새 컬렉션 이름을 입력해 주세요.")
    database = Path(db_path).expanduser()
    if not database.is_file():
        return None
    ensure_db_columns(database)
    with closing(get_db_connection(database)) as conn, conn:
        conn.row_factory = sqlite3.Row
        from app.db.connection import ensure_collection_tables
        ensure_collection_tables(conn)
        dup = conn.execute(
            "SELECT id FROM photo_collections WHERE name = ? COLLATE NOCASE AND id != ?",
            (clean_name, int(collection_id)),
        ).fetchone()
        if dup:
            raise ValueError(f"이미 '{clean_name}' 이름의 컬렉션이 존재합니다.")
        if color is not None:
            cursor = conn.execute(
                "UPDATE photo_collections SET name = ?, color = ? WHERE id = ?",
                (clean_name, color.strip() or "#4f46e5", int(collection_id)),
            )
        else:
            cursor = conn.execute(
                "UPDATE photo_collections SET name = ? WHERE id = ?",
                (clean_name, int(collection_id)),
            )
        if cursor.rowcount == 0:
            return None
    all_cols = get_all_collections(database)
    return next((c for c in all_cols if c["id"] == int(collection_id)), None)


def delete_collection(db_path: Path | str, collection_id: int) -> bool:
    """Delete a virtual collection without deleting the underlying photo analyses."""
    database = Path(db_path).expanduser()
    if not database.is_file():
        return False
    ensure_db_columns(database)
    with closing(get_db_connection(database)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        from app.db.connection import ensure_collection_tables
        ensure_collection_tables(conn)
        conn.execute("DELETE FROM photo_collection_items WHERE collection_id = ?", (int(collection_id),))
        cursor = conn.execute("DELETE FROM photo_collections WHERE id = ?", (int(collection_id),))
        return cursor.rowcount > 0


def update_collection_items(
    db_path: Path | str,
    collection_id: int,
    analysis_ids: list[int],
    action: str = "add",
) -> dict[str, Any] | None:
    """Add, remove, or set photo analysis IDs in a collection ('add' | 'remove' | 'set')."""
    database = Path(db_path).expanduser()
    if not database.is_file():
        return None
    ensure_db_columns(database)
    clean_ids = [int(aid) for aid in (analysis_ids or []) if str(aid).lstrip("-").isdigit()]
    act = (action or "add").strip().lower()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cid = int(collection_id)

    with closing(get_db_connection(database)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        from app.db.connection import ensure_collection_tables
        ensure_collection_tables(conn)
        col_row = conn.execute("SELECT id FROM photo_collections WHERE id = ?", (cid,)).fetchone()
        if not col_row:
            return None

        if act == "set":
            conn.execute("DELETE FROM photo_collection_items WHERE collection_id = ?", (cid,))
            if clean_ids:
                conn.executemany(
                    "INSERT OR IGNORE INTO photo_collection_items (collection_id, analysis_id, added_at) VALUES (?, ?, ?)",
                    [(cid, aid, now_iso) for aid in clean_ids],
                )
        elif act == "remove":
            if clean_ids:
                placeholders = ",".join("?" for _ in clean_ids)
                conn.execute(
                    f"DELETE FROM photo_collection_items WHERE collection_id = ? AND analysis_id IN ({placeholders})",
                    [cid, *clean_ids],
                )
        else:  # 'add'
            if clean_ids:
                conn.executemany(
                    "INSERT OR IGNORE INTO photo_collection_items (collection_id, analysis_id, added_at) VALUES (?, ?, ?)",
                    [(cid, aid, now_iso) for aid in clean_ids],
                )

    all_cols = get_all_collections(database)
    return next((c for c in all_cols if c["id"] == cid), None)

