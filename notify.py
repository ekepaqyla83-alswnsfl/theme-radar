#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
속보 푸시 알림
==============

collector.py 가 만든 data/news_data.json 에서 긴급도 높은 기사를 골라
텔레그램 / 슬랙 / 윈도우 알림으로 밀어준다. 대시보드를 안 보고 있어도 놓치지 않기 위한 것.

사용법
------
  python3 notify.py --setup          notify.json 설정 파일 만들기 (처음 한 번)
  python3 notify.py --test           설정이 맞는지 테스트 메시지 발송
  python3 notify.py                  아직 안 보낸 속보 발송
  python3 notify.py --dry-run        무엇이 나갈지 화면으로만 확인
  python3 notify.py --since 6        최근 6시간 기사만 대상 (기본 12)

collector.py 에서 바로 부르려면:
  python3 collector.py --source rss --hours 2 --notify

설정 (notify.json)
-----------------
  {
    "telegram": {"token": "12345:AA...", "chat_id": "123456789"},
    "slack":    {"webhook": "https://hooks.slack.com/services/..."},
    "windows_toast": true,
    "min_urgency": 3,
    "themes": [],            빈 배열이면 전체 테마. ["kr-hbm","kr-defense"] 처럼 좁힐 수 있다
    "markets": ["KR","US"],
    "quiet_hours": [1, 7],   이 시간대(KST)에는 발송하지 않는다. 끄려면 null
    "max_per_run": 10
  }

환경변수 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / SLACK_WEBHOOK 로도 지정할 수 있고,
환경변수가 설정 파일보다 우선한다.

중복 발송 방지
-------------
보낸 기사는 data/notified.json 에 제목 해시로 기록한다. 10분마다 수집을 돌려도
같은 기사가 다시 나가지 않는다. 7일 지난 기록은 자동으로 지운다.

의존성: 표준 라이브러리만.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "notify.json")
STATE_PATH = os.path.join(DATA_DIR, "notified.json")
ALERTS_PATH = os.path.join(DATA_DIR, "alerts.json")
KST = timezone(timedelta(hours=9))
STATE_TTL_DAYS = 7

DEFAULT_CONFIG = {
    "telegram": {"token": "", "chat_id": ""},
    "slack": {"webhook": ""},
    "windows_toast": True,
    "min_urgency": 3,
    "themes": [],
    "markets": ["KR", "US"],
    "quiet_hours": [1, 7],
    "max_per_run": 10,
}


# ---------------------------------------------------------------------------
# 설정 · 상태
# ---------------------------------------------------------------------------
def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))      # deep copy
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as exc:
            print(f"  [warn] notify.json 을 읽지 못했습니다: {exc}", file=sys.stderr)
    # 환경변수가 우선
    if os.environ.get("TELEGRAM_TOKEN"):
        cfg["telegram"]["token"] = os.environ["TELEGRAM_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        cfg["telegram"]["chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
    if os.environ.get("SLACK_WEBHOOK"):
        cfg["slack"]["webhook"] = os.environ["SLACK_WEBHOOK"]
    return cfg


def write_template() -> str:
    if os.path.exists(CONFIG_PATH):
        print(f"이미 있습니다: {CONFIG_PATH}")
        return CONFIG_PATH
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return CONFIG_PATH


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return {}
    cutoff = (datetime.now(KST) - timedelta(days=STATE_TTL_DAYS)).isoformat()
    return {k: v for k, v in state.items() if v >= cutoff}


def save_state(state: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def key_of(news: dict) -> str:
    """같은 기사를 다시 안 보내기 위한 식별자. 제목 정규화 + 해시."""
    norm = re.sub(r"[^0-9a-zA-Z가-힣]", "", news["title"])[:80]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 발송 채널
# ---------------------------------------------------------------------------
def _post(url: str, data: bytes, headers: dict, timeout: int = 10) -> tuple[bool, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = " " + e.read().decode("utf-8", "replace")[:120]
        except Exception:
            pass
        return False, f"HTTP {e.code}{detail}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def send_telegram(cfg: dict, text: str) -> tuple[bool, str] | None:
    tg = cfg.get("telegram") or {}
    token, chat = tg.get("token"), tg.get("chat_id")
    if not (token and chat):
        return None
    body = urllib.parse.urlencode({
        "chat_id": chat, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    return _post(f"https://api.telegram.org/bot{token}/sendMessage", body,
                 {"Content-Type": "application/x-www-form-urlencoded"})


def send_slack(cfg: dict, text: str) -> tuple[bool, str] | None:
    hook = (cfg.get("slack") or {}).get("webhook")
    if not hook:
        return None
    # 슬랙은 HTML 을 모른다 — 태그를 벗겨 보낸다
    plain = re.sub(r"<[^>]+>", "", text)
    body = json.dumps({"text": plain}, ensure_ascii=False).encode("utf-8")
    return _post(hook, body, {"Content-Type": "application/json"})


def send_windows_toast(cfg: dict, title: str, body: str) -> tuple[bool, str] | None:
    """윈도우 알림 센터에 띄운다. 파워셸만 쓰므로 추가 설치가 필요 없다."""
    if not cfg.get("windows_toast") or os.name != "nt":
        return None
    import subprocess

    def esc(s: str) -> str:
        return s.replace("'", "''")[:180]

    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$n=$t.GetElementsByTagName('text');$n.Item(0).AppendChild($t.CreateTextNode('{esc(title)}'))>$null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{esc(body)}'))>$null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'테마 레이더').Show([Windows.UI.Notifications.ToastNotification]::new($t));"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=15)
        return r.returncode == 0, (r.stderr.decode("utf-8", "replace")[:80] or "OK")
    except Exception as e:
        return False, f"{type(e).__name__}"


# ---------------------------------------------------------------------------
# 메시지 조립
# ---------------------------------------------------------------------------
URGENCY_TAG = {3: "[속보]", 2: "[중요]", 1: "[일반]"}
SENTIMENT_TAG = {"positive": "▲ 호재", "negative": "▼ 악재", "neutral": "─ 중립"}


def esc_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(news: dict) -> tuple[str, str]:
    """(텔레그램/슬랙용 본문, 윈도우 토스트용 한 줄) 을 만든다."""
    tag = URGENCY_TAG.get(news.get("urgency", 1), "")
    theme = news.get("primary_theme_name") or "미분류"
    when = (news.get("published") or "")[11:16]
    stocks = ", ".join(s["name"] for s in (news.get("related_stocks") or [])[:4])
    matched = ", ".join((news.get("themes") or [{}])[0].get("matched", [])[:4])

    lines = [f"<b>{tag} {esc_html(theme)}</b>",
             esc_html(news["title"]),
             f"{SENTIMENT_TAG.get(news.get('sentiment'), '')} · {esc_html(news.get('source',''))} · {when} KST"]
    if stocks:
        lines.append(f"관련주 {esc_html(stocks)}")
    if matched:
        lines.append(f"매칭 {esc_html(matched)}")
    if news.get("url"):
        lines.append(news["url"])
    return "\n".join(lines), f"{tag} {theme} · {news['title'][:60]}"


# ---------------------------------------------------------------------------
# 선별 · 발송
# ---------------------------------------------------------------------------
def pick(payload: dict, cfg: dict, state: dict, since_hours: int) -> list[dict]:
    cutoff = datetime.now(KST) - timedelta(hours=since_hours)
    themes = set(cfg.get("themes") or [])
    markets = set(cfg.get("markets") or ["KR", "US"])
    out = []
    for n in payload.get("news", []):
        if n.get("urgency", 0) < cfg.get("min_urgency", 3):
            continue
        if n.get("market") not in markets:
            continue
        if themes and not any(t["theme_id"] in themes for t in n.get("themes", [])):
            continue
        try:
            if datetime.fromisoformat(n["published"]) < cutoff:
                continue
        except Exception:
            pass
        if key_of(n) in state:
            continue
        out.append(n)
    # 긴급도 높은 순 → 최신 순
    out.sort(key=lambda n: (-n.get("urgency", 0), n.get("published", "")), reverse=False)
    out.sort(key=lambda n: n.get("published", ""), reverse=True)
    return out[: cfg.get("max_per_run", 10)]


def in_quiet_hours(cfg: dict) -> bool:
    q = cfg.get("quiet_hours")
    if not q:
        return False
    start, end = q
    h = datetime.now(KST).hour
    return start <= h < end if start <= end else (h >= start or h < end)


def deliver(cfg: dict, items: list[dict], dry_run: bool = False) -> list[dict]:
    """실제 발송. 보낸 기사 목록을 돌려준다."""
    sent = []
    for n in items:
        body, one_line = render(n)
        if dry_run:
            print("─" * 60)
            print(re.sub(r"<[^>]+>", "", body))
            sent.append(n)
            continue

        results = {}
        for name, fn in (("telegram", lambda: send_telegram(cfg, body)),
                         ("slack", lambda: send_slack(cfg, body)),
                         ("toast", lambda: send_windows_toast(cfg, "테마 레이더 속보", one_line))):
            r = fn()
            if r is not None:
                results[name] = r

        if not results:
            print("  [warn] 발송할 채널이 하나도 설정되지 않았습니다."
                  " python notify.py --setup 으로 notify.json 을 만들어 주세요.", file=sys.stderr)
            return sent
        ok = any(v[0] for v in results.values())
        for name, (good, why) in results.items():
            if not good:
                print(f"  [warn] {name} 발송 실패: {why}", file=sys.stderr)
        if ok:
            sent.append(n)
            print(f"  → 발송 {one_line[:70]}")
    return sent


def record_alerts(items: list[dict]) -> None:
    """대시보드가 '보낸 알림' 목록을 보여줄 수 있게 남긴다 (최근 50건)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(ALERTS_PATH, encoding="utf-8") as f:
            prev = json.load(f).get("alerts", [])
    except Exception:
        prev = []
    now = datetime.now(KST).isoformat()
    new = [{"sent_at": now, "title": n["title"], "theme": n.get("primary_theme_name"),
            "urgency": n.get("urgency"), "sentiment": n.get("sentiment"),
            "market": n.get("market"), "source": n.get("source"),
            "published": n.get("published"), "url": n.get("url", "")}
           for n in items]
    with open(ALERTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": now, "alerts": (new + prev)[:50]}, f,
                  ensure_ascii=False, indent=1)


def run(payload: dict | None = None, since_hours: int = 12,
        dry_run: bool = False, quiet: bool = False) -> int:
    """collector.py 에서도 부르는 진입점. 발송한 건수를 돌려준다."""
    cfg = load_config()
    if payload is None:
        path = os.path.join(DATA_DIR, "news_data.json")
        if not os.path.exists(path):
            print("  [warn] data/news_data.json 이 없습니다. collector.py 를 먼저 실행하세요.",
                  file=sys.stderr)
            return 0
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)

    if in_quiet_hours(cfg) and not dry_run:
        if not quiet:
            q = cfg["quiet_hours"]
            print(f"  조용한 시간({q[0]}~{q[1]}시)이라 발송을 건너뜁니다.")
        return 0

    state = load_state()
    items = pick(payload, cfg, state, since_hours)
    if not items:
        if not quiet:
            print("  발송할 새 속보가 없습니다.")
        return 0

    if not quiet:
        print(f"■ 속보 {len(items)}건 발송" + (" (미리보기)" if dry_run else ""))
    sent = deliver(cfg, items, dry_run)
    if sent and not dry_run:
        now = datetime.now(KST).isoformat()
        for n in sent:
            state[key_of(n)] = now
        save_state(state)
        record_alerts(sent)
    return len(sent)


def main() -> int:
    ap = argparse.ArgumentParser(description="테마 레이더 속보 푸시 알림")
    ap.add_argument("--setup", action="store_true", help="notify.json 설정 파일 생성")
    ap.add_argument("--test", action="store_true", help="테스트 메시지 발송")
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 내용만 출력")
    ap.add_argument("--since", type=int, default=12, help="최근 N시간 기사만 (기본 12)")
    args = ap.parse_args()

    if args.setup:
        p = write_template()
        print(f"■ 설정 파일: {p}")
        print("  텔레그램: @BotFather 로 봇을 만들고 token 을, 봇과 대화 후")
        print("            https://api.telegram.org/bot<token>/getUpdates 에서 chat_id 를 넣으세요.")
        print("  슬랙:     채널 설정 → Incoming Webhook 주소를 webhook 에 넣으세요.")
        print("  둘 다 비워도 윈도우 알림은 동작합니다.")
        return 0

    if args.test:
        cfg = load_config()
        body = ("<b>[테스트] 테마 레이더</b>\n알림 설정이 정상입니다.\n"
                f"{datetime.now(KST):%Y-%m-%d %H:%M} KST")
        any_ch = False
        for name, r in (("telegram", send_telegram(cfg, body)),
                        ("slack", send_slack(cfg, body)),
                        ("toast", send_windows_toast(cfg, "테마 레이더", "알림 설정이 정상입니다."))):
            if r is None:
                print(f"  {name:<9} 설정 없음 — 건너뜀")
                continue
            any_ch = True
            print(f"  {name:<9} {'성공' if r[0] else '실패 — ' + r[1]}")
        if not any_ch:
            print("  설정된 채널이 없습니다. python notify.py --setup 을 먼저 실행하세요.")
        return 0

    n = run(since_hours=args.since, dry_run=args.dry_run)
    print(f"■ 완료 — {n}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
