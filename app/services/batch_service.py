from __future__ import annotations

import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from app.models.analysis import PhotoAnalysis, get_score_grade
from app.services.gemini_client import analyze_with_gemini
from app.services.image_processor import PreparedPhoto, prepare_photo
from app.services.xmp_service import write_xmp_sidecar


def _dispatch_analyze(photo: PreparedPhoto, model: str, category_hint: str | None = None) -> PhotoAnalysis:
    mod = sys.modules.get("photo_analyzer")
    if mod is not None and hasattr(mod, "analyze_with_gemini"):
        fn = getattr(mod, "analyze_with_gemini")
        if fn is not analyze_with_gemini:
            return fn(photo, model=model, category_hint=category_hint)
    from app.services.multi_llm import analyze_photo, resolve_task_model
    provider, resolved_model = resolve_task_model(model)
    return analyze_photo(photo, provider=provider, model=resolved_model, category_hint=category_hint)


_dispatch_analyze_with_gemini = _dispatch_analyze


def run_batch_pipeline(
    photo_paths: list[Path],
    model: str,
    db_path: Path,
    report_dir: Path | None,
    summary_html_path: Path | None,
    max_workers: int = 2,
    category: str = "auto",
    generate_xmp: bool = False,
) -> int:
    """Analyze multiple photos in parallel, save results to DB, generate reports and optional XMP sidecars."""
    from app.config import ALL_MODEL_PRESETS
    from app.db.repository import find_existing_analysis, save_analysis
    from app.exporters.html_exporter import render_batch_comparison_html, save_html_report
    model = ALL_MODEL_PRESETS.get(model.strip().lower(), model)
    print(f"=== 피규어 사진 일괄 분석 시작 ===", file=sys.stderr)
    print(f"대상 사진: {len(photo_paths)}장 | 모델: {model} | 동시 워커: {max_workers}", file=sys.stderr)
    print(f"SQLite DB: {db_path}", file=sys.stderr)
    if report_dir:
        report_dir.mkdir(parents=True, exist_ok=True)
        print(f"개별 HTML 폴더: {report_dir}", file=sys.stderr)
    if generate_xmp:
        print("Lightroom / Capture One 호환 XMP 사이드카 자동 생성 활성화됨", file=sys.stderr)

    results: list[dict[str, Any]] = []
    report_stem_counts = Counter(
        re.sub(r"[^A-Za-z0-9._-]+", "_", photo_path.stem).strip("._") or "photo"
        for photo_path in photo_paths
    )

    def _process_one(photo_path: Path) -> dict[str, Any]:
        photo = prepare_photo(photo_path)
        existing = find_existing_analysis(db_path, photo.sha256, model=model)
        if existing is not None:
            record_id, analysis_dict = existing
            analysis = PhotoAnalysis.model_validate(analysis_dict)
        else:
            analysis = _dispatch_analyze_with_gemini(photo, model=model, category_hint=category if category != "auto" else None)
            record_id = save_analysis(db_path, photo, model, analysis)
        report_path = None
        rel_report = None
        if report_dir is not None:
            clean_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", photo_path.stem).strip("._") or "photo"
            report_name = clean_stem
            if report_stem_counts[clean_stem] > 1 or (report_dir / f"{report_name}.html").exists():
                report_name = f"{clean_stem}__{record_id}"
            report_path = report_dir / f"{report_name}.html"
            save_html_report(photo, analysis, record_id, model, report_path)
            if summary_html_path is not None:
                try:
                    rel_report = os.path.relpath(report_path, summary_html_path.parent).replace("\\", "/")
                except ValueError:
                    rel_report = report_path.as_posix()
            else:
                rel_report = report_path.as_posix()

        if generate_xmp:
            tags_list = [t for sub in analysis.aesthetic_tags.model_dump().values() for t in sub]
            write_xmp_sidecar(
                photo_path=photo_path,
                score=analysis.final_score,
                reason=analysis.final_reason,
                figure_category=analysis.figure_category,
                tags=tags_list,
                strengths=analysis.strengths,
                improvements=analysis.improvements,
            )

        return {
            "path": photo_path,
            "filename": photo_path.name,
            "photo": photo,
            "analysis": analysis,
            "record_id": record_id,
            "report_path": report_path,
            "relative_report": rel_report,
        }

    total = len(photo_paths)
    completed_count = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_map = {executor.submit(_process_one, p): p for p in photo_paths}
        for future in as_completed(future_map):
            completed_count += 1
            path = future_map[future]
            try:
                res = future.result()
                results.append(res)
                analysis: PhotoAnalysis = res["analysis"]
                grade = get_score_grade(analysis.final_score)
                print(
                    f"[{completed_count:02d}/{total}] {path.name} [{analysis.figure_category}] 완료 - {analysis.final_score:.1f}점 ({grade}) [DB #{res['record_id']}]",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(f"[{completed_count:02d}/{total}] {path.name} 분석 실패: {exc}", file=sys.stderr)

    # Sort results by filename
    results.sort(key=lambda r: r["filename"].casefold())

    if summary_html_path is not None and results:
        summary_html_path.parent.mkdir(parents=True, exist_ok=True)
        summary_content = render_batch_comparison_html(results, model, db_path)
        summary_html_path.write_text(summary_content, encoding="utf-8")
        print(f"일괄 비교 HTML 보고서 저장 완료: {summary_html_path}", file=sys.stderr)

    print(f"\n=== 일괄 분석 완료: 성공 {len(results)}/{total}장 ===", file=sys.stderr)
    return 0 if len(results) == total else 1
