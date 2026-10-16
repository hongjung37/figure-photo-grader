"""app.cli - CLI parser and entrypoint for analyzing photos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_TIER,
    ENV_FILE_PATH,
    MODEL_PRESETS,
    SUPPORTED_FORMATS,
)
from app.db import ensure_db_columns, save_analysis
from app.exporters.html_exporter import save_html_report
from app.services.batch_service import run_batch_pipeline
from app.services.gemini_client import analyze_with_gemini, set_usage_log_db
from app.services.image_processor import prepare_photo
from app.services.xmp_service import write_xmp_sidecar


def _dispatch_analyze(photo, model: str, category: str | None):
    mod = sys.modules.get("photo_analyzer")
    if mod is not None and hasattr(mod, "analyze_with_gemini"):
        fn = getattr(mod, "analyze_with_gemini")
        if fn is not analyze_with_gemini:
            return fn(photo, model=model, category_hint=category)
    return analyze_with_gemini(photo, model=model, category_hint=category)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="피규어 사진의 안전한 EXIF와 Gemini JSON 평가를 SQLite에 저장하고 보고서를 생성합니다."
    )
    parser.add_argument(
        "target",
        type=Path,
        help="분석할 사진 파일(JPEG, MPO, PNG, WEBP) 또는 사진이 포함된 폴더 경로",
    )
    parser.add_argument(
        "--category",
        "-c",
        choices=["auto", "macro", "snap", "staging", "general"],
        default="auto",
        help="피규어 촬영 세부 유형 (auto: 자동 판별, macro: 접사/디테일, snap: 일상/야외 스냅, staging: 스튜디오 연출/디오라마, general: 일반) (기본값: auto)",
    )
    parser.add_argument(
        "--tier",
        choices=list(MODEL_PRESETS.keys()),
        default=DEFAULT_TIER,
        help="Gemini 성능/비용 티어 선택 (lite: flash-lite, standard: flash, pro: pro) (기본값: standard)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="사용할 Gemini 모델명 직접 지정 (지정 시 --tier 옵션보다 우선)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB 경로 (기본값: {DEFAULT_DB_PATH.name})",
    )
    parser.add_argument(
        "--html",
        "--html-report",
        dest="html_output",
        type=Path,
        metavar="PATH",
        help="단일 사진 분석 시 단독 HTML 보고서 저장 경로",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="폴더 일괄 분석 시 동시 처리 워커 수 (기본값: 2)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="폴더 일괄 분석 시 하위 폴더까지 재귀적으로 검색",
    )
    parser.add_argument(
        "--summary-html",
        type=Path,
        default=None,
        help="폴더 일괄 분석 시 전체 비교 요약 HTML 저장 경로 (기본: <폴더>/comparison.html)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="폴더 일괄 분석 시 개별 사진 HTML 보고서를 저장할 폴더 (기본: <폴더>/reports)",
    )
    parser.add_argument(
        "--xmp",
        action="store_true",
        help="Lightroom / Capture One 호환 XMP 사이드카 파일(*.xmp)을 원본 사진 옆에 자동 생성",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_path = args.target.expanduser().resolve()
    model = args.model if args.model else MODEL_PRESETS[args.tier]
    db_path = args.db.expanduser().resolve()
    ensure_db_columns(db_path)
    set_usage_log_db(db_path)

    if target_path.is_dir():
        # Batch folder mode
        extensions = {f".{fmt.lower()}" for fmt in SUPPORTED_FORMATS} | {".jpg"}
        pattern = "**/*" if args.recursive else "*"
        photo_paths = [
            p for p in sorted(target_path.glob(pattern))
            if p.is_file() and p.suffix.lower() in extensions
        ]
        if not photo_paths:
            print(f"오류: 지정된 폴더에 지원하는 사진 파일이 없습니다: {target_path}", file=sys.stderr)
            return 1

        summary_html = (
            args.summary_html.expanduser().resolve()
            if args.summary_html
            else (args.html_output.expanduser().resolve() if args.html_output else target_path / "comparison.html")
        )
        report_dir = args.report_dir.expanduser().resolve() if args.report_dir else target_path / "reports"

        return run_batch_pipeline(
            photo_paths=photo_paths,
            model=model,
            db_path=db_path,
            report_dir=report_dir,
            summary_html_path=summary_html,
            max_workers=args.workers,
            category=args.category,
            generate_xmp=args.xmp,
        )

    # Single file mode
    try:
        if not target_path.is_file():
            candidates = list(target_path.parent.glob(f"{target_path.name}.*"))
            supported_exts = {f".{fmt.lower()}" for fmt in SUPPORTED_FORMATS} | {".jpg"}
            valid_candidates = [c for c in candidates if c.suffix.lower() in supported_exts]
            if valid_candidates:
                raise FileNotFoundError(
                    f"파일을 찾을 수 없습니다: {target_path} (혹시 '{valid_candidates[0].name}' 파일을 의미하셨나요? 확장자를 포함해 주세요.)"
                )
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {target_path}")
        report_output = args.html_output.expanduser().resolve() if args.html_output else None
        if report_output is not None:
            protected_paths = {
                target_path,
                db_path,
                ENV_FILE_PATH.resolve(),
            }
            if report_output in protected_paths:
                raise ValueError("HTML 보고서 경로가 입력 사진, SQLite DB 또는 .env 경로와 같을 수 없습니다.")
        photo = prepare_photo(target_path)
        analysis = _dispatch_analyze(photo, model=model, category=args.category if args.category != "auto" else None)
        record_id = save_analysis(db_path, photo, model, analysis)
        report_path = None
        if report_output is not None:
            report_path = save_html_report(photo, analysis, record_id, model, report_output)

        if args.xmp:
            tags_list = [t for sub in analysis.aesthetic_tags.model_dump().values() for t in sub]
            xmp_out = write_xmp_sidecar(
                photo_path=target_path,
                score=analysis.final_score,
                reason=analysis.final_reason,
                figure_category=analysis.figure_category,
                tags=tags_list,
                strengths=analysis.strengths,
                improvements=analysis.improvements,
            )
            print(f"XMP 사이드카 저장 완료: {xmp_out}", file=sys.stderr)
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    # Keep stdout as a single valid JSON document for piping to other programs.
    print(analysis.model_dump_json(indent=2))
    print(f"SQLite 저장 완료 (record_id={record_id}, db={db_path})", file=sys.stderr)
    if report_path is not None:
        print(f"HTML 보고서 저장 완료: {report_path}", file=sys.stderr)
    return 0
