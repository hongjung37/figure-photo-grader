"""app.services.burst_detector - Burst sequence detection and Best Pick clustering."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.services.image_processor import color_sig_distance

_COPY_SUFFIX_RE = re.compile(r"^(.+?)(?:[\s_-]*\(\d+\)|(?<=\d)-\d{1,2}|[\s_-]+복사본)$")


def _extract_filename_base(filename: str) -> str:
    stem = Path(filename).stem.lower()
    m = _COPY_SUFFIX_RE.match(stem)
    return m.group(1) if m else stem


def _is_copy_variant(fn1: str, fn2: str) -> bool:
    if not fn1 or not fn2:
        return False
    return _extract_filename_base(fn1) == _extract_filename_base(fn2)


def _has_large_camera_seq_gap(fn1: str, fn2: str, max_gap: int = 10) -> bool:
    """Return True if two files share the same camera prefix but have shutter numbers > max_gap apart."""
    if not fn1 or not fn2:
        return False
    b1 = _extract_filename_base(fn1)
    b2 = _extract_filename_base(fn2)
    m1 = re.search(r"(\d+)$", b1)
    m2 = re.search(r"(\d+)$", b2)
    if m1 and m2:
        p1, p2 = b1[: m1.start()], b2[: m2.start()]
        if p1 and p1 == p2:
            try:
                return abs(int(m1.group(1)) - int(m2.group(1))) > max_gap
            except ValueError:
                pass
    return False


def are_filenames_sequential(fn1: str, fn2: str) -> bool:
    """Check if filenames indicate sequential continuous shots (diff <= 1) or duplicate copy variants."""
    if not fn1 or not fn2:
        return False
    base1 = _extract_filename_base(fn1)
    base2 = _extract_filename_base(fn2)

    if base1 == base2:
        return True

    # Check trailing integer sequence (strictly consecutive: diff <= 1, e.g. IMG_0123 vs IMG_0124)
    m1 = re.search(r"(\d+)$", base1)
    m2 = re.search(r"(\d+)$", base2)
    if m1 and m2:
        prefix1 = base1[: m1.start()]
        prefix2 = base2[: m2.start()]
        if prefix1 == prefix2:
            try:
                num1 = int(m1.group(1))
                num2 = int(m2.group(1))
                if abs(num1 - num2) <= 1:
                    return True
            except ValueError:
                pass
    return False


def parse_photo_time(item: dict) -> datetime | None:
    """Extract capture time strictly from EXIF / captured_at (never falling back to DB upload created_at)."""
    captured_at = item.get("captured_at")
    if captured_at and isinstance(captured_at, str):
        try:
            return datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    exif = item.get("exif") or {}
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        val = exif.get(key)
        if val and isinstance(val, str):
            try:
                clean_val = val.replace("-", ":")
                parts = clean_val.split(" ")
                if len(parts) >= 2:
                    date_part = parts[0].replace(":", "-")
                    iso_str = f"{date_part}T{parts[1]}"
                    return datetime.fromisoformat(iso_str)
            except Exception:
                pass
    return None


def _get_time_diff_seconds(t1: datetime, t2: datetime) -> float:
    """Compute absolute seconds difference safely across naive/aware datetimes."""
    n1 = t1.replace(tzinfo=None)
    n2 = t2.replace(tzinfo=None)
    return abs((n1 - n2).total_seconds())


def _parse_focal_length(item: dict) -> float | None:
    """Extract numeric focal length (in mm) from item EXIF if available."""
    exif = item.get("exif") or {}
    val = exif.get("FocalLength")
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None
    if isinstance(val, str):
        m = re.search(r"(\d+(?:\.\d+)?)", val)
        if m:
            fv = float(m.group(1))
            return fv if fv > 0 else None
    return None


def are_burst_pair(
    item1: dict,
    item2: dict,
    base_max_dist: int = 15,
    time_window_sec: int = 180,
    max_session_gap_sec: int = 600,
) -> bool:
    """Determine if two photos belong to the same burst sequence using a hybrid
    perceptual hash, orientation/color signature, filename sequentiality, and EXIF capture metadata model.
    """
    sha1 = item1.get("sha256")
    sha2 = item2.get("sha256")
    if sha1 and sha2 and sha1 == sha2:
        return False

    h1 = item1.get("dhash")
    h2 = item2.get("dhash")
    if h1 is None or h2 is None:
        return False

    fn1 = item1.get("filename", "")
    fn2 = item2.get("filename", "")
    copy_var = _is_copy_variant(fn1, fn2)

    # Supplement 3-A: Orientation & Aspect Ratio veto
    w1, h_1 = item1.get("width"), item1.get("height")
    w2, h_2 = item2.get("width"), item2.get("height")
    if w1 and h_1 and w2 and h_2 and w1 > 0 and h_1 > 0 and w2 > 0 and h_2 > 0:
        if (w1 > h_1 * 1.05 and h_2 > w2 * 1.05) or (h_1 > w1 * 1.05 and w2 > h_2 * 1.05):
            return False
        if not copy_var:
            r1, r2 = w1 / h_1, w2 / h_2
            if abs(r1 - r2) / max(r1, r2) > 0.25:
                return False

    # Supplement 2-A: Same camera prefix with large shutter sequence gap veto
    if not copy_var and _has_large_camera_seq_gap(fn1, fn2, max_gap=10):
        return False

    # Supplement 2-B: EXIF capture time & Focal Length separation veto
    t1 = parse_photo_time(item1)
    t2 = parse_photo_time(item2)
    time_prox = False
    if t1 and t2:
        try:
            tdiff = _get_time_diff_seconds(t1, t2)
            if not copy_var and tdiff > max_session_gap_sec:
                return False
            time_prox = tdiff <= time_window_sec
        except Exception:
            pass

    fl1 = _parse_focal_length(item1)
    fl2 = _parse_focal_length(item2)
    if fl1 and fl2 and not copy_var:
        if abs(fl1 - fl2) >= 5.0 and abs(fl1 - fl2) / max(fl1, fl2) > 0.20:
            return False

    # Supplement 3-B: 2-zone RGB Color Signature veto (center subject + full frame)
    sig1 = item1.get("color_sig")
    sig2 = item2.get("color_sig")
    if sig1 is not None and sig2 is not None:
        c_dist, f_dist = color_sig_distance(int(sig1), int(sig2))
        max_rgb_diff = 80.0 if copy_var else 45.0
        if c_dist > max_rgb_diff or f_dist > max_rgb_diff:
            return False

    dist = bin(h1 ^ h2).count("1")

    # If within base threshold, it's a burst directly
    if dist <= base_max_dist:
        return True

    fn_seq = are_filenames_sequential(fn1, fn2)

    cat1 = item1.get("figure_category")
    cat2 = item2.get("figure_category")
    same_cat = bool(cat1 and cat2 and cat1 == cat2)

    bonus = 0
    if fn_seq:
        bonus += 3
    if time_prox:
        bonus += 2
    if same_cat and (fn_seq or time_prox):
        bonus += 1

    allowed_dist = min(base_max_dist + bonus, 21)
    return dist <= allowed_dist


def cluster_burst_groups(analyses: list[dict], max_hamming_dist: int = 15) -> list[dict]:
    """Cluster photos into Burst Groups using Complete-Linkage clustering to prevent
    transitive snowball chaining. Selects Best Pick (1st place) and tags B-cuts with concrete drop reasons.
    """
    if not analyses:
        return []

    n = len(analyses)
    pair_ok = [[False] * n for _ in range(n)]
    candidate_pairs: list[tuple[int, int, int, int]] = []

    for i in range(n):
        for j in range(i + 1, n):
            if are_burst_pair(analyses[i], analyses[j], base_max_dist=max_hamming_dist):
                pair_ok[i][j] = True
                pair_ok[j][i] = True
                h1 = analyses[i].get("dhash")
                h2 = analyses[j].get("dhash")
                dist = bin(h1 ^ h2).count("1") if (h1 is not None and h2 is not None) else 64
                fn_seq = are_filenames_sequential(
                    analyses[i].get("filename", ""),
                    analyses[j].get("filename", ""),
                )
                candidate_pairs.append((0 if fn_seq else 1, dist, i, j))

    # Sort pairs by strongest bond first: sequential/copy filenames first, then lowest Hamming distance
    candidate_pairs.sort()

    clusters: dict[int, list[int]] = {i: [i] for i in range(n)}
    node_to_cluster: dict[int, int] = {i: i for i in range(n)}

    # Supplement 1: Complete-Linkage merge — every member of cluster A must be a valid burst pair with every member of cluster B
    for _, _, i, j in candidate_pairs:
        ci = node_to_cluster[i]
        cj = node_to_cluster[j]
        if ci == cj:
            continue
        if all(pair_ok[u][v] for u in clusters[ci] for v in clusters[cj]):
            clusters[ci].extend(clusters[cj])
            for v in clusters[cj]:
                node_to_cluster[v] = ci
            del clusters[cj]

    groups = clusters

    focus_priority = {
        "완벽 칼초점": 1,
        "미세 앞핀": 2,
        "미세 뒤핀": 2,
        "판별 불가": 3,
        "초점 이탈": 4,
    }

    for root_id, member_indices in groups.items():
        if len(member_indices) >= 2:
            sorted_indices = sorted(
                member_indices,
                key=lambda idx: (
                    analyses[idx].get("final_score", 0),
                    -focus_priority.get(analyses[idx].get("focus_status", "완벽 칼초점"), 3),
                    analyses[idx].get("technique_score", 0),
                ),
                reverse=True,
            )
            group_id = f"burst_{min(analyses[idx]['id'] for idx in member_indices)}"
            best_idx = sorted_indices[0]
            best_item = analyses[best_idx]

            for rank, idx in enumerate(sorted_indices, start=1):
                item = analyses[idx]
                item["is_burst"] = True
                item["burst_group_id"] = group_id
                item["burst_rank"] = rank
                item["burst_total"] = len(sorted_indices)

                if rank == 1:
                    item["is_best_pick"] = True
                    item["drop_reason"] = ""
                else:
                    item["is_best_pick"] = False
                    best_f = best_item.get("focus_status", "완벽 칼초점")
                    cur_f = item.get("focus_status", "완벽 칼초점")
                    if best_f == "완벽 칼초점" and cur_f != "완벽 칼초점":
                        item["drop_reason"] = f"초점 핀 열세 ({cur_f})"
                    elif (best_item.get("lighting_score", 0) - item.get("lighting_score", 0)) >= 0.4:
                        diff = best_item.get("lighting_score", 0) - item.get("lighting_score", 0)
                        item["drop_reason"] = f"조명/노출 밸런스 열세 (-{diff:.1f}점)"
                    elif (best_item.get("composition_score", 0) - item.get("composition_score", 0)) >= 0.4:
                        diff = best_item.get("composition_score", 0) - item.get("composition_score", 0)
                        item["drop_reason"] = f"구도 안정성 열세 (-{diff:.1f}점)"
                    elif (best_item.get("technique_score", 0) - item.get("technique_score", 0)) >= 0.4:
                        diff = best_item.get("technique_score", 0) - item.get("technique_score", 0)
                        item["drop_reason"] = f"기술/선예도 디테일 열세 (-{diff:.1f}점)"
                    else:
                        score_diff = best_item.get("final_score", 0) - item.get("final_score", 0)
                        item["drop_reason"] = f"종합 점수 차이 (-{score_diff:.1f}점)" if score_diff > 0 else "미세 디테일 차이"
        else:
            idx = member_indices[0]
            analyses[idx]["is_burst"] = False
            analyses[idx]["is_best_pick"] = False
            analyses[idx]["burst_group_id"] = None
            analyses[idx]["burst_rank"] = 1
            analyses[idx]["burst_total"] = 1
            analyses[idx]["drop_reason"] = ""

    return analyses
