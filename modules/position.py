"""Module E — 建倉與補倉系統"""
from typing import Dict, Any, Optional

ACTION_BUY = "建倉"
ACTION_ADD = "補倉"
ACTION_HOLD = "持有"
ACTION_REDUCE = "減碼"
ACTION_AVOID = "不建議投入"


def calculate(
    fundamental_score: float,
    risk_level: str,
    valuation_status: str,
    ma200_bias: Optional[float],
    cost_basis: Optional[float] = None,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Generate position action recommendation.

    Args:
        cost_basis:    user's average cost (optional) for add/reduce triggers
        current_price: current market price
    """

    rules: list[str] = []
    action = ACTION_HOLD

    # ── Entry decision based on fundamental score ────────────────────────────
    if fundamental_score >= 85:
        action = ACTION_BUY
        strategy = "長期定投，可分批建倉"
        batch_suggestion = "建議分 6–12 個月分批投入，每月定額"
        rules.append("基本面評分 85+ — 優質長期標的，適合積極建倉")
    elif fundamental_score >= 70:
        action = ACTION_BUY
        strategy = "小部位建倉，持續觀察"
        batch_suggestion = "建議先投入 30–50%，剩餘待基本面確認後補入"
        rules.append("基本面評分 70–84 — 可觀察建倉")
    elif fundamental_score >= 50:
        action = ACTION_HOLD
        strategy = "觀察為主，暫不加碼"
        batch_suggestion = "可保留 5–10% 小部位觀察"
        rules.append("基本面評分 50–69 — 風險偏高，保守對待")
    else:
        action = ACTION_AVOID
        strategy = "不建議投入"
        batch_suggestion = "基本面不符合長期投資標準"
        rules.append("基本面評分 < 50 — 不建議長期投入")

    # ── 估值過熱覆寫：好公司也要等好價格 ─────────────────────────────
    overheated = (valuation_status == "過熱") or (ma200_bias is not None and ma200_bias > 20)
    if overheated and action == ACTION_BUY:
        # 基本面好但估值偏高 → 改成觀望、等回檔
        action = ACTION_HOLD
        if valuation_status == "過熱":
            strategy = "基本面優質但估值過熱，等待回檔再分批建倉"
        else:
            strategy = f"基本面優質但 MA200 乖離 +{ma200_bias:.0f}% 偏高，等待回檔"
        batch_suggestion = "暫不進場；列入觀察清單，待估值合理或股價回到 MA200 附近再分批建倉"
        rules.append("估值/股價過熱 — 雖然基本面優異，仍應等待較佳進場點")

    # ── Add position trigger (if holding) ───────────────────────────────────
    add_triggered = False
    add_condition = ""
    if cost_basis and current_price and cost_basis > 0:
        pnl_pct = (current_price - cost_basis) / cost_basis * 100
        if pnl_pct <= -10 and fundamental_score >= 70:
            add_triggered = True
            add_condition = f"持有成本 {cost_basis:.2f}，現價下跌 {abs(pnl_pct):.1f}%（超過 -10%），基本面未惡化 → 啟動補倉"
            rules.append(add_condition)
            if action not in (ACTION_AVOID,):
                action = ACTION_ADD
        elif pnl_pct <= -20 and fundamental_score >= 50:
            add_triggered = True
            add_condition = f"現價下跌 {abs(pnl_pct):.1f}%（超過 -20%）→ 強力補倉訊號"
            rules.append(add_condition)

    # ── Reduce position trigger ──────────────────────────────────────────────
    reduce_triggered = False
    reduce_reasons = []
    if valuation_status == "過熱":
        reduce_triggered = True
        reduce_reasons.append("估值過熱")
    if ma200_bias and ma200_bias > 20:
        reduce_triggered = True
        reduce_reasons.append(f"MA200乖離率 +{ma200_bias:.1f}%（超過+20%）")
    if fundamental_score < 50 and action != ACTION_AVOID:
        reduce_triggered = True
        reduce_reasons.append("基本面惡化")

    if reduce_triggered:
        reduce_condition = "、".join(reduce_reasons) + " → 建議分批減碼 20–30%"
        rules.append(reduce_condition)
        if action == ACTION_HOLD:
            action = ACTION_REDUCE

    # ── Position sizing suggestion ───────────────────────────────────────────
    if risk_level == "保守型":
        max_position_pct = "5–10%"
    elif risk_level == "中性型":
        max_position_pct = "10–20%"
    else:
        max_position_pct = "5–10%（高風險需控制）"

    # ── Action color ─────────────────────────────────────────────────────────
    action_color = {
        ACTION_BUY: "green",
        ACTION_ADD: "blue",
        ACTION_HOLD: "gray",
        ACTION_REDUCE: "orange",
        ACTION_AVOID: "red",
    }

    return {
        "action": action,
        "action_color": action_color[action],
        "strategy": strategy,
        "batch_suggestion": batch_suggestion,
        "max_position_pct": max_position_pct,
        "add_triggered": add_triggered,
        "reduce_triggered": reduce_triggered,
        "rules": rules,
    }
