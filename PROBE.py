#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시세 소스 진단기 (PROBE.bat 이 부르는 파일)
==========================================

quotes.py 가 실제로 쓰는 후보 주소 목록을 그대로 하나씩 찔러 보고, 어디가 살아있는지
표로 찍는다. 결과는 화면과 PROBE_RESULT.txt 에 동시에 남는다.

  python PROBE.py

지수·환율 시세가 비어 보일 때 어느 소스가 죽었는지 확인하는 용도다.
진단 로직은 quotes.py 안에 있어, 후보 주소가 늘어나도 여기는 고칠 필요가 없다
— 진단기와 실제 수집기가 같은 목록을 보게 하려는 것이 이 파일의 목적이다.

읽기 전용 조회만 하며 아무것도 바꾸지 않는다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from quotes import diagnose
except ImportError as exc:      # quotes.py 가 없거나 깨졌을 때
    print("[오류] quotes.py 를 읽지 못했습니다:", exc)
    print("       폴더 안에 quotes.py 가 있는지 확인해 주세요.")
    sys.exit(1)

if __name__ == "__main__":
    sys.exit(diagnose())
