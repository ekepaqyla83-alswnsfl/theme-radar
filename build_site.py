#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages 에 올릴 사이트를 만든다 (_site 폴더).

  python build_site.py

PC 에서 쓰는 dashboard.html 은 데이터를 파일 안에 통째로 박아둔다 — 더블클릭으로
열어도 뭔가 보이게 하려는 것이다. 하지만 웹에 올릴 때는 그게 독이 된다.
갱신이 실패했을 때 몇 시간 전 숫자를 아무 표시 없이 보여주게 되기 때문이다.

그래서 웹용 사본에서는 박아둔 데이터를 비우고, data/*.json 만 보게 한다.
못 읽으면 화면에 '데이터 없음'이 뜬다 — 오래된 숫자를 최신인 척 보여주는 것보다 낫다.
"""

from __future__ import annotations

import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "_site")
DATA_DIR = os.path.join(BASE_DIR, "data")

FOOTER_WEB = (
    "테마 분류는 키워드 가중 스코어링 기반 자동 분류 결과이며, 투자 판단의 근거가 아닙니다.<br>"
    "30분마다 자동 갱신됩니다 (평일 장중 기준). 화면 상단의 시각이 마지막 갱신 시점입니다."
)


def strip_embedded(html: str) -> str:
    """dashboard.html 안에 박아둔 데이터 블록을 비운다."""
    for start, end, var in (("/*DATA_START*/", "/*DATA_END*/", "EMBEDDED_DATA"),
                            ("/*QUOTES_START*/", "/*QUOTES_END*/", "EMBEDDED_QUOTES")):
        a, b = html.find(start), html.find(end)
        if a == -1 or b == -1:
            print(f"  [warn] {var} 블록을 찾지 못했습니다 — 그대로 둡니다.")
            continue
        html = html[: a + len(start)] + f"\nconst {var} = null;\n" + html[b:]
    return html


def swap_footer(html: str) -> str:
    """PC 용 실행 안내 대신 웹용 안내로 바꾼다."""
    m = re.search(r"<footer>(.*?)</footer>", html, re.S)
    if not m:
        print("  [warn] footer 를 찾지 못했습니다 — 그대로 둡니다.")
        return html
    return html[: m.start()] + f"<footer>\n    {FOOTER_WEB}\n  </footer>" + html[m.end():]


def main() -> int:
    src = os.path.join(BASE_DIR, "dashboard.html")
    if not os.path.exists(src):
        print("[오류] dashboard.html 이 없습니다.")
        return 1

    if os.path.isdir(SITE_DIR):
        shutil.rmtree(SITE_DIR)
    os.makedirs(os.path.join(SITE_DIR, "data"), exist_ok=True)

    with open(src, encoding="utf-8") as f:
        html = f.read()
    html = swap_footer(strip_embedded(html))
    out = os.path.join(SITE_DIR, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  index.html  {os.path.getsize(out):,} bytes (원본 {os.path.getsize(src):,})")

    # 대시보드가 읽는 데이터와 엑셀 리포트만 올린다.
    # notified.json(발송 이력)·source_map.json(내부 캐시)은 공개할 이유가 없다.
    for name in ("news_data.json", "quotes.json", "alerts.json", "theme_report.xlsx"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(SITE_DIR, "data", name))
            print(f"  data/{name}  {os.path.getsize(p):,} bytes")
        else:
            print(f"  data/{name}  없음 — 건너뜀")

    with open(os.path.join(SITE_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nDisallow: /\n")     # 검색엔진에 잡히지 않게

    print(f"\n완료: {SITE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
