from __future__ import annotations

"""main.py - Unified CLI entrypoint for Figure Photo Grader.

Usage:
    python main.py analyze <target> [--tier lite|standard|pro] [--category auto|macro|snap|staging|general] [--xmp]
    python main.py serve [--port 8080] [--db path/to/db]
    python main.py export export|import|tags [--db path] [--output path]
    python main.py <target> (shorthand for analyze)
"""

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("사용법:")
        print("  python main.py analyze <사진/폴더> [옵션]")
        print("  python main.py serve [--port 8080] [--db 경로]")
        print("  python main.py export [export|import|tags] [옵션]")
        return 0

    subcommand = args[0].lower()

    if subcommand in ("serve", "server", "dashboard"):
        from app.web.server import main as server_main
        return server_main(args[1:])

    if subcommand in ("export", "excel"):
        from app.exporters.excel_exporter import main as export_main
        return export_main(args[1:])

    if subcommand in ("analyze", "eval"):
        import photo_analyzer
        return photo_analyzer.main(args[1:])

    if subcommand in ("-h", "--help"):
        print("피규어 사진 평가 및 큐레이션 통합 CLI (Figure Photo Grader)")
        print("\n사용 가능한 서브커맨드:")
        print("  analyze   사진 또는 폴더를 분석하여 SQLite 저장 및 HTML 보고서 생성")
        print("  serve     웹 큐레이션 및 리뷰 대시보드 서버 실행")
        print("  export    Excel 보고서 내보내기/가져오기 및 태그 통계")
        print("\n단일 파일/폴더 분석 단축 실행:")
        print("  python main.py <사진파일 또는 폴더> [옵션]")
        return 0

    # Default to photo_analyzer if a path or option is passed directly
    import photo_analyzer
    return photo_analyzer.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
