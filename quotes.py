#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
주요지수 · 환율 실시간 티커 수집기
==================================

사용법
------
  python3 quotes.py                       # 샘플 시세 (오프라인 구조 검증)
  python3 quotes.py --source auto         # 실시세 — 후보 소스를 순서대로 시도 (권장)
  python3 quotes.py --source auto --watch 30   # 30초마다 갱신 (Ctrl+C 종료)
  python3 quotes.py --diag                # 어느 시세 주소가 살아있는지 진단표 출력

출력
----
  data/quotes.json      : dashboard.html 티커가 읽는 시세 데이터
  data/source_map.json  : 종목별로 '성공했던 주소'를 기억해 다음 실행을 빠르게 한다

설계 메모
--------
무료 시세는 예고 없이 죽는다. 그래서 종목마다 후보 주소를 여러 개 두고 순서대로 찔러,
처음 성공한 곳을 쓰고 그 주소를 source_map.json 에 기억한다. 기억해 둔 주소가 나중에
죽으면 자동으로 다음 후보로 넘어간다 — 코드를 고칠 필요가 없다.

실패한 종목은 값을 지어내지 않는다. quotes.json 에 `"ok": false` 로 남기고
대시보드는 그 자리를 '—' 로 비운다. 시세가 없는 것과 0인 것은 다르다.

선물(코스피200 주야간, 해외 선물)은 다루지 않는다. 지수·환율·원자재·금리만 본다.

세션 구분 (KST)
--------------
  동시호가 08:30~09:00 / 정규장 09:00~15:30 / 그 외 마감·휴장

의존성: 표준 라이브러리만.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MAP_PATH = os.path.join(DATA_DIR, "source_map.json")
KST = timezone(timedelta(hours=9))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 사이트별 요청 헤더. 네이버 비공식 API는 Referer/Origin 이 없으면 409 로 막는다.
HEADER_SETS = {
    "naver_m": {"User-Agent": UA, "Referer": "https://m.stock.naver.com/",
                "Origin": "https://m.stock.naver.com",
                "Accept": "application/json, text/plain, */*"},
    "naver_f": {"User-Agent": UA, "Referer": "https://finance.naver.com/",
                "Accept": "application/json, text/plain, */*"},
    "yahoo":   {"User-Agent": UA, "Accept": "application/json"},
}

# ---------------------------------------------------------------------------
# 1. 종목 정의
# ---------------------------------------------------------------------------
PINNED = ["ndx", "kospi", "usdkrw"]

INSTRUMENTS = [
    # 국내 지수
    dict(id="kospi",    name="코스피",      group="국내 지수", yahoo="^KS11",  naver="KOSPI",  dec=2),
    dict(id="kosdaq",   name="코스닥",      group="국내 지수", yahoo="^KQ11",  naver="KOSDAQ", dec=2),
    dict(id="kospi200", name="코스피200",   group="국내 지수", yahoo="^KS200", naver="KPI200", dec=2),

    # 해외 지수
    dict(id="spx",  name="S&P500",          group="해외 지수", yahoo="^GSPC", dec=2),
    dict(id="ndx",  name="나스닥",           group="해외 지수", yahoo="^IXIC", dec=2),
    dict(id="dji",  name="다우",             group="해외 지수", yahoo="^DJI",  dec=2),
    dict(id="sox",  name="필라델피아 반도체",  group="해외 지수", yahoo="^SOX",  dec=2),
    dict(id="n225", name="니케이225",        group="해외 지수", yahoo="^N225", dec=2),
    dict(id="hsi",  name="항셍",             group="해외 지수", yahoo="^HSI",  dec=2),
    # 미국에 상장된 한국 주식 ETF. 한국이 밤일 때 미국에서 거래되므로
    # '간밤에 외국인이 한국을 어떻게 봤는지'를 아침에 확인하는 용도.
    dict(id="ewy", name="한국 ETF(EWY)", group="해외 지수", yahoo="EWY", dec=2),

    # 환율 · 원자재 · 금리 · 심리
    dict(id="usdkrw", name="원/달러",     group="환율·원자재", yahoo="KRW=X",    naver="FX_USDKRW", dec=2),
    dict(id="dxy",    name="달러인덱스",   group="환율·원자재", yahoo="DX-Y.NYB", dec=2),
    dict(id="wti",    name="WTI 유가",    group="환율·원자재", yahoo="CL=F",     dec=2),
    dict(id="gold",   name="금",          group="환율·원자재", yahoo="GC=F",     dec=1),
    dict(id="ust10",  name="미 국채 10년", group="채권·심리",  yahoo="^TNX",     dec=3, unit="%"),
    dict(id="vix",    name="VIX",         group="채권·심리",  yahoo="^VIX",     dec=2),
    dict(id="btc",    name="비트코인",     group="채권·심리",  yahoo="BTC-USD",  dec=0),
]

for _i in INSTRUMENTS:
    _i["pin"] = _i["id"] in PINNED


# ---------------------------------------------------------------------------
# 2. 장 세션 판정
# ---------------------------------------------------------------------------
def market_session(now: datetime | None = None) -> dict:
    """KST 기준 국내 증시 세션."""
    now = now or datetime.now(KST)
    t, weekday = now.time(), now.weekday() < 5      # 월=0

    if not weekday:
        code, label = "holiday", "휴장 (주말)"
    elif dtime(8, 30) <= t < dtime(9, 0):
        code, label = "pre", "장 시작 전 (동시호가)"
    elif dtime(9, 0) <= t < dtime(15, 30):
        code, label = "regular", "정규장 진행 중"
    else:
        code, label = "closed", "정규장 마감"
    return {"code": code, "label": label, "now": now.isoformat(),
            "hint": {"regular": "09:00~15:30",
                     "pre": "08:30~09:00 동시호가",
                     "closed": "다음 개장 대기",
                     "holiday": "주말·공휴일 휴장"}[code]}


# ---------------------------------------------------------------------------
# 3. HTTP + 값 추출 유틸
# ---------------------------------------------------------------------------
def http(url: str, headers: str = "yahoo", body: str | None = None,
         timeout: int = 10) -> bytes:
    data = body.encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADER_SETS[headers],
                                 method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _f(v) -> float | None:
    """'1,234.56', '+3.2%', 1234 → float. 못 읽으면 None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,%\s+]", "", str(v)).replace("−", "-")
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# 사이트마다 키 이름이 다르다. 현재가 후보 / 전일종가 후보 / 대비 후보를 각각 나열해 두고
# 응답 어디에 있든 찾아 쓴다. 새 소스가 생겨도 키 이름만 여기 추가하면 된다.
LAST_KEYS = ("closePrice", "nowVal", "currentValue", "calcPrice", "tradePrice",
             "regularMarketPrice", "TDD_CLSPRC", "ISU_PRC", "curPrice", "price")
PREV_KEYS = ("previousClosePrice", "prevClosePrice", "chartPreviousClose",
             "previousClose", "BAS_PRC", "PRV_DD_CLSPRC", "prevPrice")
CHG_KEYS = ("compareToPreviousClosePrice", "changeVal", "CMPPREVDD_PRC",
            "change", "compareToPreviousPrice")


def _dig(obj, keys: tuple[str, ...]):
    """중첩된 dict/list 어디에 있든 keys 중 하나의 값을 찾아 float 으로 돌려준다."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                v = _f(obj[k])
                if v is not None:
                    return v
        for v in obj.values():
            got = _dig(v, keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _dig(v, keys)
            if got is not None:
                return got
    return None


def rows_of(obj) -> list[dict]:
    """응답에서 '종목 행 목록'으로 보이는 리스트를 찾아낸다 (KRX/네이버 목록 응답용)."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj
    if isinstance(obj, dict):
        for key in ("output", "OutBlock_1", "datas", "result", "items", "list"):
            v = obj.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in obj.values():
            got = rows_of(v)
            if got:
                return got
    return []


def quote_from(obj, row_match: str | None = None) -> dict | None:
    """임의의 JSON 응답에서 (현재가, 전일종가)를 뽑는다.

    row_match 가 있으면 먼저 그 정규식에 맞는 행을 고른다. 목록 형태로 오는 응답에서
    원하는 종목 한 줄만 집어내기 위한 것.
    """
    target = obj
    if row_match:
        rows = rows_of(obj)
        pat = re.compile(row_match)
        cand = [r for r in rows if any(isinstance(v, str) and pat.search(v) for v in r.values())]
        if not cand:
            return None
        # 여러 만기가 잡히면 거래량이 가장 많은 행 = 최근월물
        def vol(r):
            return _dig(r, ("ACC_TRDVOL", "accTradeVolume", "TRDVOL", "volume")) or 0
        target = max(cand, key=vol)

    last = _dig(target, LAST_KEYS)
    if last is None:
        return None
    prev = _dig(target, PREV_KEYS)
    if prev is None:
        chg = _dig(target, CHG_KEYS)
        prev = last - chg if chg is not None else None
    if prev is None or prev == 0:
        return None
    return {"last": last, "prev": prev}


# ---------------------------------------------------------------------------
# 4. 후보 소스 레지스트리
# ---------------------------------------------------------------------------
# 각 후보: (라벨, URL, 헤더세트, POST바디, 행선택 정규식)
# 위에서부터 시도하고 처음 성공한 것을 쓴다.
def index_candidates(code: str) -> list[tuple]:
    if code.startswith("FX_"):
        c = code[3:]
        return [
            (f"네이버 환율 {c}(m)", f"https://m.stock.naver.com/api/marketindex/exchange/{c}", "naver_m", None, None),
            (f"네이버 환율 {c}(api)", f"https://api.stock.naver.com/marketindex/exchange/{c}", "naver_m", None, None),
        ]
    return [
        (f"네이버 지수 {code}(m)", f"https://m.stock.naver.com/api/index/{code}/basic", "naver_m", None, None),
        (f"네이버 지수 {code}(api)", f"https://api.stock.naver.com/index/{code}/basic", "naver_m", None, None),
        (f"네이버 polling {code}", f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}", "naver_f", None, None),
    ]


def yahoo_candidates(sym: str) -> list[tuple]:
    q = urllib.parse.quote(sym)
    return [
        (f"야후 {sym}", f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=5d&interval=1d", "yahoo", None, None),
        (f"야후2 {sym}", f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?range=5d&interval=1d", "yahoo", None, None),
    ]


def candidates_for(inst: dict, source: str) -> list[tuple]:
    """이 종목을 어디서 받아올지 후보 목록. 국내는 네이버 먼저, 그다음 야후."""
    out: list[tuple] = []
    if source in ("auto", "naver") and inst.get("naver"):
        out += index_candidates(inst["naver"])
    if source in ("auto", "yahoo") and inst.get("yahoo"):
        out += yahoo_candidates(inst["yahoo"])
    if source == "naver":
        out = [c for c in out if "야후" not in c[0]]
    if source == "yahoo":
        out = [c for c in out if "야후" in c[0]] or out
    return out


# ---------------------------------------------------------------------------
# 5. 샘플 시세 (오프라인 구조 검증용)
# ---------------------------------------------------------------------------
SAMPLE_BASE = {
    "kospi": (6579.4, 6345.9), "kosdaq": (912.3, 911.2), "kospi200": (878.4, 847.1),
    "spx": (7412.8, 7385.1), "ndx": (25130.6, 24902.4), "dji": (49210.3, 49355.8),
    "sox": (8942.1, 8760.5), "n225": (54120.0, 53880.5), "hsi": (27310.2, 27455.9),
    "ewy": (82.4, 81.2),
    "usdkrw": (1348.20, 1355.60), "dxy": (97.42, 97.81), "wti": (66.35, 65.90),
    "gold": (4218.5, 4195.0), "ust10": (4.082, 4.135), "vix": (15.42, 16.88),
    "btc": (118420, 115900),
}


def build_sample(seed: int | None = None) -> dict[str, dict]:
    rng = random.Random(seed)
    now = datetime.now(KST).isoformat()
    out = {}
    for inst in INSTRUMENTS:
        last, prev = SAMPLE_BASE[inst["id"]]
        # 호출할 때마다 미세하게 흔들어 실시간 갱신을 눈으로 확인할 수 있게 한다
        out[inst["id"]] = {"last": round(last * (1 + rng.uniform(-0.0012, 0.0012)), 6),
                           "prev": prev, "time": now, "src": "sample", "via": "샘플"}
    return out


# ---------------------------------------------------------------------------
# 6. 수집
# ---------------------------------------------------------------------------
def load_map() -> dict:
    try:
        with open(MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_map(m: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def try_candidate(cand: tuple, timeout: int = 10) -> tuple[dict | None, str]:
    """후보 하나를 시도한다. (시세 or None, 사유)"""
    label, url, hdr, body, row = cand
    try:
        raw = http(url, hdr, body, timeout)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}"
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None, "JSON 아님"
    q = quote_from(obj, row)
    return (q, "OK") if q else (None, "값 없음")


def collect(source: str, verbose: bool = True) -> dict[str, dict]:
    if source == "sample":
        return build_sample()

    smap = load_map()
    quotes: dict[str, dict] = {}
    now = datetime.now(KST).isoformat()

    for inst in INSTRUMENTS:
        iid = inst["id"]
        cands = candidates_for(inst, source)
        # 지난번에 성공했던 주소를 맨 앞으로 — 매번 처음부터 훑지 않는다
        remembered = smap.get(iid)
        if remembered:
            cands = sorted(cands, key=lambda c: c[1] != remembered)

        for cand in cands:
            q, why = try_candidate(cand)
            if q:
                quotes[iid] = {**q, "time": now, "src": cand[2].split("_")[0], "via": cand[0]}
                smap[iid] = cand[1]
                break
            if verbose:
                print(f"  [skip] {inst['name']} ← {cand[0]}: {why}", file=sys.stderr)
        else:
            if verbose:
                print(f"  [실패] {inst['name']} — 후보 {len(cands)}개 모두 실패", file=sys.stderr)
            smap.pop(iid, None)

    save_map(smap)
    return quotes


# ---------------------------------------------------------------------------
# 7. 조립 · 출력
# ---------------------------------------------------------------------------
def assemble(quotes: dict[str, dict]) -> dict:
    session = market_session()
    groups: dict[str, list] = {}
    items_by_id: dict[str, dict] = {}
    missing: list[str] = []

    for inst in INSTRUMENTS:
        q = quotes.get(inst["id"])
        base = {"id": inst["id"], "name": inst["name"], "group": inst["group"],
                "dec": inst["dec"], "unit": inst.get("unit", ""),
                "pin": inst.get("pin", False)}
        if not q:
            # 값을 지어내지 않는다. 대시보드가 '—' 로 비워 그릴 수 있게 표시만 남긴다.
            missing.append(inst["name"])
            item = {**base, "ok": False, "last": None, "change": None, "pct": None,
                    "time": None, "src": "none", "via": "수집 실패"}
        else:
            chg = q["last"] - q["prev"]
            pct = (chg / q["prev"] * 100) if q["prev"] else 0.0
            item = {**base, "ok": True,
                    "last": round(q["last"], inst["dec"]), "change": round(chg, inst["dec"]),
                    "pct": round(pct, 2), "time": q["time"], "src": q["src"],
                    "via": q.get("via", "")}
        items_by_id[inst["id"]] = item
        groups.setdefault(inst["group"], []).append(item)

    srcs = sorted({i["src"] for i in items_by_id.values() if i["ok"]})
    return {
        "updated": datetime.now(KST).isoformat(),
        "session": session,
        "ticker": [i for i in items_by_id.values() if i["pin"]],
        "groups": [{"name": g, "items": v} for g, v in groups.items()],
        "source": "+".join(srcs) if srcs else "none",
        "missing": missing,
    }


def write(payload: dict) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "quotes.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def inject(payload: dict) -> str | None:
    """dashboard.html 의 시세 블록 교체 (오프라인에서도 티커가 뜨도록)."""
    path = os.path.join(BASE_DIR, "dashboard.html")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        src = f.read()
    a, b = src.find("/*QUOTES_START*/"), src.find("/*QUOTES_END*/")
    if a == -1 or b == -1:
        return None
    new = (src[: a + len("/*QUOTES_START*/")] + "\nconst EMBEDDED_QUOTES = "
           + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n" + src[b:])
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return path


def print_board(p: dict) -> None:
    s = p["session"]
    print(f"\n■ {s['label']}  ({s['hint']})   {p['updated'][11:19]} KST   소스 {p['source']}")
    for g in p["groups"]:
        print(f"\n  [{g['name']}]")
        for i in g["items"]:
            if not i["ok"]:
                print(f"    {i['name']:<22} {'—':>12}   (수집 실패)")
                continue
            arrow = "▲" if i["change"] > 0 else "▼" if i["change"] < 0 else "─"
            print(f"    {i['name']:<22} {i['last']:>12,.{i['dec']}f}{i['unit']:<2} "
                  f"{arrow} {i['change']:>+9,.{i['dec']}f}  {i['pct']:>+7.2f}%")
    if p.get("missing"):
        print(f"\n  ※ 수집 실패 {len(p['missing'])}건: {', '.join(p['missing'])}")
        print("    → python quotes.py --diag 로 어느 주소가 살아있는지 확인할 수 있습니다.")


def diagnose() -> int:
    """모든 후보 주소를 하나씩 찔러 결과를 표로 출력한다 (PROBE.bat 이 부르는 진단기).

    화면과 PROBE_RESULT.txt 에 동시에 쓴다 — 중간에 끊겨도 파일은 남는다.
    """
    out_path = os.path.join(BASE_DIR, "PROBE_RESULT.txt")
    buf: list[str] = []

    def say(line: str = "") -> None:
        print(line)
        buf.append(line)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(buf))
        except Exception:
            pass

    say("=" * 78)
    say(" 시세 소스 진단 — 살아있는 주소를 찾습니다")
    say(f" python {sys.version.split()[0]} · {datetime.now(KST):%Y-%m-%d %H:%M} KST")
    say("=" * 78)

    alive: dict[str, str] = {}
    for inst in INSTRUMENTS:
        cands = candidates_for(inst, "auto")
        if not cands:
            continue
        say(f"\n▸ {inst['name']}")
        for cand in cands:
            q, why = try_candidate(cand, timeout=8)
            mark = "OK  " if q else "실패"
            extra = (f"  last={q['last']:,.2f} prev={q['prev']:,.2f}" if q else f"  ({why})")
            say(f"   [{mark}] {cand[0]}{extra}")
            if q:
                alive.setdefault(inst["id"], cand[0])
                break        # 살아있는 곳을 찾았으면 나머지는 볼 필요 없다

    bad = [i for i in INSTRUMENTS if i["id"] not in alive]
    say("\n" + "=" * 78)
    say(f" 성공 {len(alive)}종목 / 실패 {len(bad)}종목")
    for i in bad:
        say(f"   ✗ {i['name']}")
    if bad:
        say("\n 실패한 종목이 있으면 이 파일을 통째로 복사해 보내주세요. 파서를 맞춰 드립니다.")
    say(f" 결과 파일: {out_path}")
    say("=" * 78)

    try:
        if os.name == "nt":
            os.startfile(out_path)          # type: ignore[attr-defined]
    except Exception:
        pass
    return 0


def _safe_console() -> None:
    """출력하다 죽지 않게 한다.

    콘솔이 표현 못 하는 글자가 하나라도 있으면 print 가 UnicodeEncodeError 를 내며
    프로그램이 통째로 죽는다 — 30초마다 도는 갱신이 조용히 멈추는 원인이 된다.
    인코딩은 콘솔 것을 그대로 두고(바꾸면 한글이 깨진다) 실패만 '?' 로 넘긴다.
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")     # py3.7+
        except Exception:
            pass


def main() -> int:
    _safe_console()
    ap = argparse.ArgumentParser(description="주요지수 · 환율 티커 수집기")
    ap.add_argument("--source", choices=["sample", "yahoo", "naver", "auto"], default="sample")
    ap.add_argument("--watch", type=int, metavar="SEC", help="N초마다 반복 갱신")
    ap.add_argument("--quiet", action="store_true", help="시세판 출력 생략")
    ap.add_argument("--no-inject", action="store_true", help="dashboard.html 갱신 생략")
    ap.add_argument("--diag", action="store_true", help="후보 시세 주소 진단표 출력 후 종료")
    args = ap.parse_args()

    if args.diag:
        return diagnose()

    fails = 0
    while True:
        try:
            payload = assemble(collect(args.source, verbose=not args.quiet))
            write(payload)
            if not args.no_inject:
                inject(payload)
            if not args.quiet:
                print_board(payload)
            fails = 0
        except KeyboardInterrupt:
            print("\n종료합니다.")
            return 0
        except Exception as exc:
            # --watch 로 몇 시간씩 도는 도중 한 번 삐끗했다고 창이 죽으면 안 된다.
            # 무엇 때문에 넘어갔는지만 남기고 다음 주기에 다시 시도한다.
            fails += 1
            print(f"\n  [오류] 이번 회차 갱신 실패 ({fails}회 연속): "
                  f"{type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr)
            if not args.watch:
                return 1
            if fails >= 20:
                print("  20회 연속 실패라 종료합니다. 위 오류를 확인해 주세요.", file=sys.stderr)
                return 1

        if not args.watch:
            return 0
        try:
            time.sleep(max(5, args.watch))
        except KeyboardInterrupt:
            print("\n종료합니다.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
