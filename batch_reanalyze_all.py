"""batch_reanalyze_all.py - Safe batch reanalyzer strictly honoring Gemini 15 RPM limit."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import threading
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
    parser.add_argument("--concurrency", "-c", type=int, default=1, help="Concurrent workers (e.g. 1, 2, 3, 5, 10, 50)")
    parser.add_argument("--only-flash-lite", action="store_true", help="Only reanalyze photos currently using flash lite")
    args = parser.parse_args()

    model_arg = args.model
    provider, resolved_model = resolve_task_model(model_arg, default_tier="luna")
    delay_sec = 4.3 if "gemini" in resolved_model else args.delay

    print(f"=== [{resolved_model}] 일괄 재분석 시작 ===")
    print(f"제공자: {provider} | 동시 병렬: {args.concurrency}개 | 요청 간 대기: {delay_sec}초 | 대상: {'Flash-Lite 대상만' if args.only_flash_lite else '전체'}")
    print(f"DB 경로: {DB_PATH.resolve()}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if args.only_flash_lite:
            cur.execute("SELECT id, source_filename, model, analysis_json FROM photo_analyses WHERE model LIKE '%flash-lite%' ORDER BY id ASC")
        else:
            cur.execute("SELECT id, source_filename, model, analysis_json FROM photo_analyses ORDER BY id ASC")
        rows = cur.fetchall()

    total = len(rows)
    print(f"총 분석 대상: {total}개 레코드\n")

    results: list[dict[str, Any]] = []
    start_time = time.time()
    completed_count = 0
    progress_lock = threading.Lock()

    def _process_single_row(item: tuple[int, sqlite3.Row]) -> dict[str, Any] | None:
        nonlocal completed_count
        idx, r = item
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
            with progress_lock:
                completed_count += 1
                print(f"[{completed_count}/{total}] ID {record_id} ({filename}): 로드 실패 (건너뜀)")
            return None

        try:
            prep = _load_prepared_photo_for_record(DB_PATH, row_full)
        except Exception as e:
            with progress_lock:
                completed_count += 1
                print(f"[{completed_count}/{total}] ID {record_id} ({filename}): 이미지 로드 에러 ({e})")
            return None

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
                    with progress_lock:
                        print(f"  [429 Quota] {attempt}/{MAX_RETRIES}회 재시도 대기 ({wait_time}초)...")
                    time.sleep(wait_time)
                else:
                    with progress_lock:
                        print(f"  [Error] {filename} 분석 중 예외 발생: {e}")
                    if attempt == MAX_RETRIES:
                        break
                    time.sleep(3.0)

        if not new_analysis:
            with progress_lock:
                completed_count += 1
                print(f"[{completed_count}/{total}] ID {record_id} ({filename}): 분석 실패")
            return None

        # Save to database
        update_analysis(DB_PATH, record_id, resolved_model, new_analysis)

        new_score = float(new_analysis.final_score)
        new_cat = new_analysis.figure_category
        diff = round(new_score - old_score, 2)
        diff_str = f"+{diff}" if diff > 0 else f"{diff}"

        # Progress & ETA calculation
        with progress_lock:
            completed_count += 1
            curr_done = completed_count
            elapsed = time.time() - start_time
            avg_per_item = elapsed / curr_done
            remaining_items = total - curr_done
            remaining_seconds = int(avg_per_item * remaining_items)
            rem_min = remaining_seconds // 60
            rem_sec = remaining_seconds % 60

            msg = (
                f"[{curr_done:03d}/{total:03d}] ({curr_done/total*100:4.1f}%) {filename[:25]:<25} | "
                f"구: {old_score:4.1f}점 -> 신: {new_score:4.1f}점 ({diff_str:>5}) | "
                f"카테고리: {new_cat} | ETA: {rem_min}분 {rem_sec:02d}초"
            )
            print(msg, flush=True)

        if args.concurrency <= 1:
            req_duration = time.time() - req_start
            if req_duration < delay_sec:
                time.sleep(delay_sec - req_duration)

        return {
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
        }

    indexed_rows = list(enumerate(rows, start=1))
    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            for item_result in executor.map(_process_single_row, indexed_rows):
                if item_result:
                    results.append(item_result)
    else:
        for row_item in indexed_rows:
            item_result = _process_single_row(row_item)
            if item_result:
                results.append(item_result)

    # Save JSON Report
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_time = time.time() - start_time
    print(f"\n=== 전수 재분석 완료! (총 소요 시간: {int(total_time//60)}분 {int(total_time%60)}초) ===", flush=True)
    print(f"결과 JSON 저장됨: {REPORT_JSON_PATH}", flush=True)


if __name__ == "__main__":
    main()
