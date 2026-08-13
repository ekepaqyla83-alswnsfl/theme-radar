#!/usr/bin/env bash
# macOS / Linux 실행 스크립트
#   chmod +x start.sh  후  ./start.sh
set -u
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python) || {
  echo "[오류] 파이썬이 없습니다. https://www.python.org/downloads/"; exit 1; }

echo "[1/4] 파이썬 확인 ($PY)"
$PY -c "import openpyxl" 2>/dev/null || { echo "[2/4] 엑셀 모듈 설치..."; $PY -m pip install openpyxl --quiet; }
echo "[2/4] 패키지 확인 완료"

echo "[3/4] 뉴스 수집 중..."
NOTIFY=""
[ -f notify.json ] && NOTIFY="--notify"      # 알림 설정이 있으면 속보 푸시도 함께
$PY collector.py --source rss --hours 24 --xlsx $NOTIFY

echo "[4/4] 대시보드 실행..."
$PY -m http.server 8765 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 2
(open http://localhost:8765/dashboard.html 2>/dev/null || xdg-open http://localhost:8765/dashboard.html 2>/dev/null) &

echo
echo "대시보드: http://localhost:8765/dashboard.html"
echo "종료하려면 Ctrl+C"
echo
$PY quotes.py --source auto --watch 30
