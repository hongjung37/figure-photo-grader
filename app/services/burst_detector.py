"""app.services.burst_detector - Burst sequence detection and Best Pick clustering."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def are_filenames_sequential(fn1: str, fn2: str) -> bool:
    """Check if filenames indicate sequential continuous shots or duplicate copy variants."""
    s1 = Path(fn1).stem.lower()
    s2 = Path(fn2).stem.lower()

    if s1 == s2:
        return True

    # Check copy suffix e.g. "sg_01089-2" vs "sg_01089" or "sg_03607 (1)" vs "sg_03607"
    copy_pattern = r"^(.+?)(?:[\s_-]*\(\d+\)|[\s_-]+\d{1,2}|[\s_-]+복사본)$"
    m_copy1 = re.match(copy_pattern, s1)
    base1 = m_copy1.group(1) if m_copy1 else s1

    m_copy2 = re.match(copy_pattern, s2)
    base2 = m_copy2.group(1) if m_copy2 else s2

    if base1 == base2 or base1 == s2 or base2 == s1:
        return True

    # Check trailing integer sequence (e.g. IMG_0123 vs IMG_0124)
    m1 = re.search(r"(\d+)$", s1)
    m2 = re.search(r"(\d+)$", s2)
    if m1 and m2:
        prefix1 = s1[: m1.start()]
        prefix2 = s2[: m2.start()]
        if prefix1 == prefix2:
            try:
                num1 = int(m1.group(1))
                num2 = int(m2.group(1))
                if abs(num1 - num2) <= 3:
                    return True
            except ValueError:
                pass
    return False


def parse_photo_time(item: dict) -> datetime | None:
    """Extract capture time from the dedicated field, EXIF, or DB created_at."""
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
    created = item.get("created_at")
    if created and isinstance(created, str):
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            pass
    return None


def are_burst_pair(
    item1: dict,
    item2: dict,
    base_max_dist: int = 15,
    time_window_sec: int = 15,
) -> bool:
    """Determine if two photos belong to the same burst sequence using a hybrid
    perceptual hash, filename sequentiality, and timestamp proximity model.
    """
    sha1 = item1.get("sha256")
    sha2 = item2.get("sha256")
    if sha1 and sha2 and sha1 == sha2:
        return False

    h1 = item1.get("dhash")
    h2 = item2.get("dhash")
    if h1 is None or h2 is None:
        return False

    dist = bin(h1 ^ h2).count("1")

    # Very close perceptual matches are safe without metadata support.
    if dist <= min(base_max_dist, 8):
        return True

    fn_seq = are_filenames_sequential(item1.get("filename", ""), item2.get("filename", ""))

    t1 = parse_photo_time(item1)
    t2 = parse_photo_time(item2)
    time_prox = False
    if t1 and t2:
        try:
            ts1 = t1.timestamp()
            ts2 = t2.timestamp()
            time_prox = abs(ts1 - ts2) <= time_window_sec
        except Exception:
            pass

    cat1 = item1.get("figure_category")
    cat2 = item2.get("figure_category")
    same_cat = bool(cat1 and cat2 and cat1 == cat2)

    # Wider visual differences require both burst-like filename and timing
    # evidence; category alone must not pull unrelated photos together.
    if fn_seq and time_prox:
        allowed_dist = min(base_max_dist + 12, 30)
        return dist <= allowed_dist

    return False


def cluster_burst_groups(analyses: list[dict], max_hamming_dist: int = 15) -> list[dict]:
    """Cluster photos into Burst Groups based on perceptual dHash similarity,
    filename sequence, and timestamp proximity.
    Selects Best Pick (1st place) and tags B-cuts with concrete drop reasons.
    """
    if not analyses:
        return []

    n = len(analyses)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(n):
        for j in range(i + 1, n):
            if are_burst_pair(analyses[i], analyses[j], base_max_dist=max_hamming_dist):
                union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        r = find(idx)
        groups.setdefault(r, []).append(idx)

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
