"""batch_reanalyze_all.py - Safe batch reanalyzer strictly honoring Gemini 15 RPM limit."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import argparse
from app.db.repository import get_analysis_row_by_id, update_analysis
from app.services.multi_llm import analyze_photo, resolve_task_model
from app.web.handlers import _load_prepared_photo_for_record

DB_PATH = Path("data/photo_analysis.sqlite3")
REPORT_JSON_PATH = Path("outputs/reanalysis_report_20261018.json")
REPORT_MD_PATH = Path("outputs/reanalysis_report_20261018.md")
DEFAULT_MODEL_NAME = "gpt-6-luna"
RPM_DELAY_SECONDS = 1.5  # Luna doesn't have the 15 RPM Free limit of Gemini
MAX_RETRIES = 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch reanalyze figure photos")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME, help="Model to use (e.g. gpt-6-luna, luna, standard)")
    parser.add_argument("--delay", type=float, default=RPM_DELAY_SECONDS, help="Delay between requests in seconds")
    args = parser.parse_args()

    model_arg = args.model
    provider, resolved_model = resolve_task_model(model_arg, default_tier="luna")
    delay_sec = 4.3 if "gemini" in resolved_model else args.delay

    print(f"=== [{resolved_model}] 107장 전수 재분석 시작 ===")
    print(f"제공자: {provider} | 요청 간 대기: {delay_sec}초")
    print(f"DB 경로: {DB_PATH.resolve()}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, source_filename, model, analysis_json FROM photo_analyses ORDER BY id ASC")
        rows = cur.fetchall()

    total = len(rows)
    print(f"총 분석 대상: {total}개 레코드\n")

    results: list[dict[str, Any]] = []
    start_time = time.time()

    for idx, r in enumerate(rows, start=1):
        record_id = r["id"]
        filename = r["source_filename"]
        old_model = r["model"]
        try:
            old_analysis = json.loads(r["analysis_json"])
            old_score = float(old_analysis.get("final_score", 0.0))
            old_cat = old_analysis.get("figure_category", "미지정")
        except Exception:
            old_score = 0.0
            old_cat = "파싱 실패"

        row_full = get_analysis_row_by_id(DB_PATH, record_id)
        if not row_full:
            print(f"[{idx}/{total}] ID {record_id} ({filename}): 로드 실패 (건너뜀)")
            continue

        try:
            prep = _load_prepared_photo_for_record(DB_PATH, row_full)
        except Exception as e:
            print(f"[{idx}/{total}] ID {record_id} ({filename}): 이미지 로드 에러 ({e})")
            continue

        # Analysis with retry logic
        new_analysis = None
        for attempt in range(1, MAX_RETRIES + 1):
            req_start = time.time()
            try:
                new_analysis = analyze_photo(
                    photo=prep,
                    provider=provider,
                    model=resolved_model,
                    category_hint=None,
                    sample_count=1,
                )
                break
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                    wait_time = 15.0 * attempt
                    print(f"  [429 Quota] {attempt}/{MAX_RETRIES}회 재시도 대기 ({wait_time}초)...")
                    time.sleep(wait_time)
                else:
                    print(f"  [Error] {filename} 분석 중 예외 발생: {e}")
                    if attempt == MAX_RETRIES:
                        break
                    time.sleep(3.0)

        if not new_analysis:
            print(f"[{idx}/{total}] ID {record_id} ({filename}): 분석 실패")
            continue

        # Save to database
        update_analysis(DB_PATH, record_id, resolved_model, new_analysis)

        new_score = float(new_analysis.final_score)
        new_cat = new_analysis.figure_category
        diff = round(new_score - old_score, 2)
        diff_str = f"+{diff}" if diff > 0 else f"{diff}"

        # Progress & ETA calculation
        elapsed = time.time() - start_time
        avg_per_item = elapsed / idx
        remaining_items = total - idx
        remaining_seconds = int(avg_per_item * remaining_items)
        rem_min = remaining_seconds // 60
        rem_sec = remaining_seconds % 60

        msg = (
            f"[{idx:03d}/{total:03d}] ({idx/total*100:4.1f}%) {filename[:25]:<25} | "
            f"구: {old_score:4.1f}점 -> 신: {new_score:4.1f}점 ({diff_str:>5}) | "
            f"카테고리: {new_cat} | ETA: {rem_min}분 {rem_sec:02d}초"
        )
        print(msg, flush=True)

        results.append({
            "id": record_id,
            "filename": filename,
            "old_model": old_model,
            "old_score": old_score,
            "old_category": old_cat,
            "new_score": new_score,
            "new_category": new_cat,
            "score_diff": diff,
            "focus_status": new_analysis.focus_status,
            "composition_score": new_analysis.composition_score,
            "lighting_score": new_analysis.lighting_score,
            "color_score": new_analysis.color_score,
            "technique_score": new_analysis.technique_score,
            "final_reason": new_analysis.final_reason,
            "strengths": new_analysis.strengths,
            "improvements": new_analysis.improvements,
        })

        # Throttle delay
        req_duration = time.time() - req_start
        if req_duration < delay_sec:
            time.sleep(delay_sec - req_duration)

    # Save JSON Report
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_time = time.time() - start_time
    print(f"\n=== 전수 재분석 완료! (총 소요 시간: {int(total_time//60)}분 {int(total_time%60)}초) ===", flush=True)
    print(f"결과 JSON 저장됨: {REPORT_JSON_PATH}", flush=True)


if __name__ == "__main__":
    main()
