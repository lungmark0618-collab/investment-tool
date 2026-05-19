"""Module D — 資金配置系統"""
from typing import Dict, Any, Optional


def calculate(
    monthly_budget: float,
    valuation_status: str,
    ma200_bias: Optional[float],
    risk_level: str,
    fundamental_score: float,
    market_mult: float = 1.0,
    market_regime: Optional[str] = None,
    existing_position_months: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Determine this month's invest ratio based on valuation and market position.

    Returns:
        invest_ratio: fraction of monthly_budget to invest (0.0 – 2.0)
        cash_ratio:   fraction to keep as cash
        invest_amount: actual dollar amount
        extra_buy:    whether to trigger extra top-up
        rationale:    list of reasoning strings
    """

    rationale = []

    # ── Base ratio from MA200 bias ──────────────────────────────────────────
    if ma200_bias is not None:
        if ma200_bias > 15:
            base_ratio = 0.50
            rationale.append(f"MA200乖離 +{ma200_bias:.1f}%（過熱），降低投入至50%")
        elif ma200_bias > 5:
            base_ratio = 0.75
            rationale.append(f"MA200乖離 +{ma200_bias:.1f}%（偏高），投入75%")
        elif ma200_bias >= -10:
            base_ratio = 1.00
            rationale.append(f"MA200乖離 {ma200_bias:+.1f}%（合理），正常投入100%")
        elif ma200_bias >= -20:
            base_ratio = 1.50
            rationale.append(f"MA200乖離 {ma200_bias:.1f}%（低估），加碼至150%")
        else:
            base_ratio = 2.00
            rationale.append(f"MA200乖離 {ma200_bias:.1f}%（大幅低估），額外補倉200%")
    else:
        base_ratio = 1.00
        rationale.append("均線資料不足，採正常投入100%")

    # ── Adjust for valuation status ─────────────────────────────────────────
    val_adjust = {
        "明顯低估": +0.25,
        "合理": 0.0,
        "高估": -0.25,
        "過熱": -0.50,
    }
    adj = val_adjust.get(valuation_status, 0.0)
    if adj != 0:
        rationale.append(f"估值「{valuation_status}」，比例調整 {adj:+.0%}")
    base_ratio = max(0.0, base_ratio + adj)

    # ── Adjust for risk level ────────────────────────────────────────────────
    risk_adjust = {"保守型": -0.10, "中性型": 0.0, "高風險型": -0.20}
    r_adj = risk_adjust.get(risk_level, 0.0)
    if r_adj != 0:
        rationale.append(f"風險等級「{risk_level}」，比例調整 {r_adj:+.0%}")
    invest_ratio = max(0.0, min(2.0, base_ratio + r_adj))

    # ── Fundamental quality gate ─────────────────────────────────────────────
    if fundamental_score < 50:
        invest_ratio = min(invest_ratio, 0.30)
        rationale.append("基本面評分偏低（< 50），上限30%")
    elif fundamental_score < 70:
        invest_ratio = min(invest_ratio, 0.80)
        rationale.append("基本面評分中等，上限80%")

    # ── Market regime overlay ───────────────────────────────────────────────
    if market_mult and abs(market_mult - 1.0) > 1e-9:
        prev = invest_ratio
        invest_ratio = max(0.0, min(2.0, invest_ratio * market_mult))
        regime_tag = f"「{market_regime}」" if market_regime else ""
        rationale.append(
            f"大盤狀態{regime_tag}乘數 ×{market_mult:.2f}，比例 {prev:.0%} → {invest_ratio:.0%}"
        )

    # ── 既有持倉 overlay：部位過大時降低投入 ─────────────────────────────
    if existing_position_months is not None and existing_position_months > 0:
        rationale.append(f"目前持倉相當於 {existing_position_months:.1f} 個月預算")
        if existing_position_months > 10:
            prev = invest_ratio
            invest_ratio *= 0.5
            rationale.append(
                f"持倉部位龐大（> 10 個月預算），投入 ×0.5：{prev:.0%} → {invest_ratio:.0%}"
            )
        elif existing_position_months > 5:
            prev = invest_ratio
            invest_ratio *= 0.8
            rationale.append(
                f"持倉部位偏重（> 5 個月預算），投入 ×0.8：{prev:.0%} → {invest_ratio:.0%}"
            )

    invest_amount = monthly_budget * invest_ratio
    cash_ratio = max(0.0, 1.0 - invest_ratio)
    extra_buy = ma200_bias is not None and ma200_bias <= -20

    # ── Monthly schedule recommendation ─────────────────────────────────────
    if invest_ratio <= 0:
        schedule = "本月暫不投入，保留現金等待估值回檔或盤勢修正"
    elif invest_ratio < 0.3:
        schedule = "本月僅小額試水（< 30%），分批謹慎進場"
    elif invest_ratio >= 1.5:
        schedule = "本月建議一次性投入（低估機會）"
    elif invest_ratio >= 1.0:
        schedule = "本月建議月初一次投入"
    else:
        schedule = "本月建議分2批投入（月初/月中）"

    return {
        "invest_ratio": round(invest_ratio, 2),
        "cash_ratio": round(cash_ratio, 2),
        "invest_amount": round(invest_amount, 0),
        "cash_reserve": round(monthly_budget * cash_ratio, 0),
        "extra_buy": extra_buy,
        "schedule": schedule,
        "rationale": rationale,
        "monthly_budget": monthly_budget,
    }
