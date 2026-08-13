#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
테마 레이더 진단기
==================

인터넷이 필요 없는 것부터 순서대로 확인해서, 어느 단계에서 막히는지 찾는다.
결과는 화면과 data/diagnose_result.txt 에 동시에 남고 메모장으로 열린다.

  python diagnose.py

배치 파일이 아니라 파이썬으로 만든 이유: cmd 배치 파일은 한글이 들어가면
파싱이 깨진다(명령 중간부터 읽는다). 안내문이 긴 작업은 전부 여기서 한다.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "diagnose_result.txt")

_buf: list[str] = []


def say(line: str = "") -> None:
    """화면과 파일에 동시에 쓴다. 중간에 죽어도 파일은 남는다."""
    try:
        print(line)
    except Exception:                      # 콘솔 인코딩 문제로 죽지 않게
        print(line.encode("ascii", "replace").decode("ascii"))
    _buf.append(line)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8-sig") as f:   # 메모장 호환
            f.write("\n".join(_buf))
    except Exception:
        pass


def run(label: str, args: list[str], timeout: int = 180) -> int:
    """자식 프로세스를 돌리고 출력을 그대로 옮겨 적는다."""
    say(f"$ {' '.join(args)}")
    # 자식 출력을 파이프로 받으면 파이썬은 콘솔이 아니라 지역 인코딩(cp949)으로 쓴다.
    # 그대로 UTF-8 로 읽으면 한글이 깨지므로, 자식에게 UTF-8 로 쓰라고 지정한다.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(args, cwd=BASE_DIR, capture_output=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        say(f"  [시간초과] {timeout}초 안에 끝나지 않았습니다.")
        return -1
    except Exception as exc:
        say(f"  [실행 실패] {type(exc).__name__}: {exc}")
        return -1
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    for line in (out + err).splitlines():
        say("  " + line)
    say(f"  → 종료코드 {p.returncode}")
    say()
    return p.returncode


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    say("=" * 66)
    say(" 테마 레이더 진단")
    say(f" {datetime.now():%Y-%m-%d %H:%M:%S}")
    say("=" * 66)
    say()

    # ---------- 1. 파이썬 ----------
    say("---------- 1. 파이썬 ----------")
    say(f"  실행파일 : {sys.executable}")
    say(f"  버전     : {sys.version.split()[0]}")
    say(f"  OS       : {platform.platform()}")
    say(f"  콘솔 인코딩: {getattr(sys.stdout, 'encoding', '?')}")
    say(f"  작업 폴더 : {BASE_DIR}")
    say()

    # ---------- 2. 파일 ----------
    say("---------- 2. 파일 확인 ----------")
    need = ["collector.py", "quotes.py", "notify.py", "themes.json", "dashboard.html"]
    missing = []
    for f in need:
        p = os.path.join(BASE_DIR, f)
        if os.path.exists(p):
            say(f"  OK   {f}  ({os.path.getsize(p):,} bytes)")
        else:
            say(f"  없음 {f}")
            missing.append(f)
    say(f"  data 폴더: {'있음' if os.path.isdir(DATA_DIR) else '없음'}")
    say()
    if missing:
        say(f"  [!] 파일이 빠져 있습니다: {', '.join(missing)}")
        say("      압축을 풀지 않고 zip 안에서 실행하면 이렇게 됩니다.")
        say()

    # ---------- 3. 엑셀 모듈 ----------
    say("---------- 3. 엑셀 모듈(openpyxl) ----------")
    try:
        import openpyxl                                   # noqa: F401
        say(f"  OK  버전 {openpyxl.__version__}")
    except ImportError:
        say("  없음 — 엑셀 리포트만 생략되고 나머지는 정상 동작합니다.")
        say("       설치하려면: pip install openpyxl")
    say()

    py = [sys.executable]

    # ---------- 4. 오프라인 실행 ----------
    say("---------- 4. 오프라인 실행 (인터넷 불필요) ----------")
    say("여기서 실패하면 코드나 설치 문제입니다.")
    say()
    rc_q = run("시세", py + ["quotes.py", "--source", "sample", "--no-inject"], 60)
    rc_c = run("뉴스", py + ["collector.py", "--source", "sample", "--no-inject"], 120)

    # ---------- 5. 인터넷 ----------
    say("---------- 5. 인터넷 연결 (매체 RSS만, 구글 검색 없이) ----------")
    say("여기서만 실패하면 방화벽·백신·사내망 문제입니다.")
    say()
    rc_net = run("RSS", py + ["collector.py", "--source", "rss", "--hours", "48",
                              "--search-limit", "0", "--no-inject"], 180)

    # ---------- 결론 ----------
    say("=" * 66)
    say(" 결론")
    say("=" * 66)
    if missing:
        say(" ✕ 파일이 빠져 있습니다. 폴더를 다시 받아 주세요.")
    elif rc_q != 0 or rc_c != 0:
        say(" ✕ 오프라인 실행부터 실패합니다. 위 4번 항목의 오류 메시지가 원인입니다.")
    elif rc_net == 0:
        say(" ○ 전부 정상입니다. UPDATE_NEWS.bat 으로 뉴스를 갱신하시면 됩니다.")
    elif rc_net == 2:
        say(" △ 프로그램은 멀쩡한데 뉴스를 한 건도 못 받았습니다.")
        say("   회사망·백신·방화벽이 뉴스 사이트를 막고 있을 가능성이 큽니다.")
        say("   위 5번 항목의 실패 메시지를 보면 어디서 막혔는지 나옵니다.")
    else:
        say(" △ 인터넷 수집 단계에서 문제가 있습니다. 위 5번 항목을 확인해 주세요.")
    say()
    say(f" 이 파일을 통째로 복사해 보내주세요: {OUT_PATH}")
    say("=" * 66)

    try:
        if os.name == "nt":
            os.startfile(OUT_PATH)          # type: ignore[attr-defined]
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
