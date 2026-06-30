"""
켈리 비율 산출 로직 (모듈에서 분리한 순수 계산 유틸).

스펙 (docs/module_spec.md · M-3-1):
  Full Kelly = (승률 × 배당 - 패율) / 배당
  Half-Kelly = Full Kelly / 2

여기서:
  승률 p   : 투자가 성공(상승)할 확률 (0~1)
  패율 q   : 1 - p
  배당 b   : 손익비 (b = 기대 상승폭 / 기대 하락폭, 즉 odds)
             예) 성공 시 +30%, 실패 시 -15% 라면 b = 0.30 / 0.15 = 2.0
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KellyResult:
    win_prob: float        # 승률 p
    loss_prob: float       # 패율 q (= 1 - p)
    odds: float            # 손익비 b
    full_kelly: float      # Full Kelly 비율 (음수 가능 = 베팅 비권장)
    half_kelly: float      # Half-Kelly 비율
    recommended_pct: float # 권장 비중(%) — 음수는 0으로 클리핑


def calc_kelly(win_prob: float, odds: float) -> KellyResult:
    """
    Full/Half Kelly 비율을 계산한다.

    Args:
        win_prob: 승률 p (0~1)
        odds:     손익비 b (= 기대수익 / 기대손실). 0보다 커야 한다.

    Returns:
        KellyResult — 권장 비중은 Half-Kelly 기준, 음수면 0%로 클리핑.
    """
    p = max(0.0, min(1.0, float(win_prob)))
    q = 1.0 - p
    b = float(odds)

    if b <= 0:
        full = 0.0
    else:
        # Full Kelly = (승률 × 배당 - 패율) / 배당
        full = (p * b - q) / b

    half = full / 2.0
    recommended = max(0.0, half) * 100.0  # %, 음수(베팅 비권장)는 0으로

    return KellyResult(
        win_prob=p,
        loss_prob=q,
        odds=b,
        full_kelly=full,
        half_kelly=half,
        recommended_pct=round(recommended, 2),
    )


def odds_from_payoffs(expected_gain_pct: float, expected_loss_pct: float) -> float:
    """
    기대 상승폭/하락폭(%)으로부터 손익비 b를 계산한다.

    Args:
        expected_gain_pct: 성공 시 기대 수익률(%), 양수
        expected_loss_pct: 실패 시 기대 손실률(%), 양수로 입력 (예: 15 → -15% 손실)

    Returns:
        손익비 b. 손실폭이 0이면 0 반환.
    """
    loss = abs(float(expected_loss_pct))
    if loss == 0:
        return 0.0
    return abs(float(expected_gain_pct)) / loss
