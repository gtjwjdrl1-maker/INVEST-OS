"""
모듈 공통 인터페이스 규약.

각 모듈 파일은 아래 세 가지를 반드시 포함해야 한다:
  MODULE_ID   : str   — 모듈 고유 ID (예: "m2_1_dart_cutoff")
  MODULE_META : dict  — {title, step, icon, default_visible, description}
  render(state) -> None  — Streamlit 컴포넌트를 그리는 단일 진입점
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.state import AppState


def validate_module(module) -> list[str]:
    """모듈이 규약을 지키는지 검사. 오류 메시지 리스트 반환 (빈 리스트 = 정상)."""
    errors: list[str] = []
    if not hasattr(module, "MODULE_ID") or not isinstance(module.MODULE_ID, str):
        errors.append("MODULE_ID (str) 누락")
    if not hasattr(module, "MODULE_META") or not isinstance(module.MODULE_META, dict):
        errors.append("MODULE_META (dict) 누락")
    else:
        for key in ("title", "step", "icon", "default_visible", "description"):
            if key not in module.MODULE_META:
                errors.append(f"MODULE_META['{key}'] 누락")
    if not callable(getattr(module, "render", None)):
        errors.append("render(state) 함수 누락")
    return errors


# MODULE_META 스키마 참조
META_SCHEMA = {
    "title":           "str  — 사이드바·카드에 표시되는 모듈 이름",
    "step":            "int  — 속한 Step (1~4). 0=대시보드, -1=설정",
    "icon":            "str  — 이모지 또는 ti-xxx 아이콘 이름",
    "default_visible": "bool — 처음 실행 시 기본 노출 여부",
    "description":     "str  — 한 줄 모듈 설명",
}
