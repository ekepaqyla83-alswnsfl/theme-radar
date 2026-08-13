#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
테마 레이더 실행기 (RUN.bat 이 부르는 파일)
==========================================

  1) 엑셀 모듈 확인
  2) 뉴스 1회 수집
  3) 웹서버 띄우고 브라우저 열기
  4) 시세 30초마다 갱신 (Ctrl+C 로 종료)

예전에는 이 순서를 RUN.bat 안에서 처리했는데, 배치 파일에 한글이 들어가면
cmd 가 파일을 읽는 위치를 놓쳐 명령이 잘려 실행된다(`echo` → `cho`).
그래서 배치는 영문 몇 줄만 남기고 실제 로직과 안내문은 전부 여기로 옮겼다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
URL = f"http://localhost:{PORT}/dashboard.html"


def step(n: int, text: str) -> None:
    print(f"\n[{n}/4] {text}")


def ensure_openpyxl() -> None:
    try:
        import openpyxl                                   # noqa: F401
        print("      엑셀 모듈 확인 완료")
    except ImportError:
        print("      엑셀 모듈 설치 중... (처음 한 번만)")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"],
                           timeout=180)
        except Exception as exc:
            print(f"      설치 실패 — 엑셀 리포트만 생략됩니다 ({exc})")


def serve() -> threading.Thread | None:
    """대시보드용 로컬 웹서버. 파일을 직접 열면 브라우저가 data/*.json 을 못 읽는다."""
    try:
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *a):      # 접속 로그로 화면을 더럽히지 않게
                pass

        os.chdir(BASE_DIR)
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Quiet)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return t
    except OSError as exc:
        print(f"      포트 {PORT} 를 열지 못했습니다 ({exc}).")
        print("      이미 떠 있는 창이 있으면 그걸 쓰시면 됩니다.")
        return None


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    print("=" * 60)
    print("  테마 레이더 — 주식 테마 분류 & 뉴스속보")
    print("=" * 60)
    print(f"  파이썬 {sys.version.split()[0]}")

    step(1, "패키지 확인")
    ensure_openpyxl()

    step(2, "뉴스 수집 중... (1~3분, 진행 상황이 한 줄씩 찍힙니다)")
    cmd = [sys.executable, "collector.py", "--source", "rss", "--hours", "24", "--xlsx"]
    if os.path.exists(os.path.join(BASE_DIR, "notify.json")):
        cmd.append("--notify")
    rc = subprocess.run(cmd, cwd=BASE_DIR).returncode
    if rc != 0:
        print("\n      뉴스를 못 받았습니다. 이전 데이터로 화면을 띄웁니다.")
        print("      기록: data\\last_run_log.txt")
        print("      원인을 보려면 DIAGNOSE.bat 을 실행해 주세요.")

    step(3, "대시보드 실행")
    if serve():
        time.sleep(1)
        try:
            webbrowser.open(URL)
        except Exception:
            pass
        print(f"      {URL}")

    step(4, "시세 갱신 시작 (30초마다)")
    print("=" * 60)
    print("  이 창을 닫으면 시세 갱신이 멈춥니다.")
    print("  종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 60)

    try:
        subprocess.run([sys.executable, "quotes.py", "--source", "auto", "--watch", "30"],
                       cwd=BASE_DIR)
    except KeyboardInterrupt:
        pass
    print("\n종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
