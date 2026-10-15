from __future__ import annotations

import argparse
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.config import DEFAULT_DB_PATH, PORT
from app.services.gemini_client import set_usage_log_db
from app.web.handlers import DashboardRequestHandler


def run_dashboard(port: int = PORT, db_path: Path = DEFAULT_DB_PATH) -> None:
    DashboardRequestHandler.db_path = db_path.resolve()
    set_usage_log_db(DashboardRequestHandler.db_path)
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardRequestHandler)
    print(f"============================================================")
    print(f" 피규어 포토 그레이더 Culling 대시보드 서버가 시작되었습니다.")
    print(f" 접속 주소: http://localhost:{port}")
    print(f" 연동 DB: {db_path.resolve()}")
    print(f" 종료하려면 Ctrl+C를 누르세요.")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n대시보드 서버를 종료합니다.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="피규어 사진 Culling & Review Web 대시보드를 실행합니다.")
    parser.add_argument("--port", type=int, default=PORT, help=f"웹 서버 포트 (기본값: {PORT})")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"연동할 SQLite DB 경로 (기본값: {DEFAULT_DB_PATH.name})",
    )
    args = parser.parse_args(argv)
    run_dashboard(port=args.port, db_path=args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
