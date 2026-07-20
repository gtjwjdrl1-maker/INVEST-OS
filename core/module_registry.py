"""
모듈 레지스트리 — 새 모듈은 여기 한 줄만 추가하면 앱에 자동 등록된다.

등록 순서:
  1. 모듈 파일을 modules/ 에 생성 (MODULE_ID, MODULE_META, render 규약 준수)
  2. 아래 import 한 줄 추가
  3. _MODULES 리스트에 모듈 추가
"""
from __future__ import annotations

# ── 모듈 import ──────────────────────
from modules import m1_2_core_scanner
from modules import m1_4_nps_tracker
from modules import m1_5_nps_backtest
from modules import m2_1_dart_cutoff
from modules import m2_2_stress_test
from modules import m3_1_ai_debate
from modules import m3_2_investment_journal
from modules import m4_1_weight_monitor
from modules import m4_2_briefing

# ── 등록 목록 ────────────────────────────────────────────────────────
_MODULES: list = [
    m1_2_core_scanner,
    m1_4_nps_tracker,
    m1_5_nps_backtest,
    m2_1_dart_cutoff,
    m2_2_stress_test,
    m3_1_ai_debate,
    m3_2_investment_journal,
    m4_1_weight_monitor,
    m4_2_briefing,
]


def get_all_modules() -> list:
    return list(_MODULES)


def get_modules_for_step(step: int) -> list:
    return [m for m in _MODULES if m.MODULE_META.get("step") == step]
