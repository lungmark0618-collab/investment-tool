"""Module F — 多標的資產配置

依據各標的的基本面分數、風險等級、估值狀態，計算建議資金配置權重。
"""
from typing import List, Dict, Any


RISK_MULT = {"保守型": 1.2, "中性型": 1.0, "高風險型": 0.7}
# key 必須對應 valuation.calculate() 實際產出的 status 字串
# （"明顯低估" / "合理" / "高估" / "過熱"），否則 .get() 會默默退回 1.0
VAL_MULT = {"明顯低估": 1.3, "合理": 1.0, "高估": 0.7, "過熱": 0.3}
EXCLUDE_ACTIONS = {"不建議投入", None, ""}


def _norm(stocks: List[Dict[str, Any]]) -> float:
    return sum(s["raw_weight"] for s in stocks) or 1.0


def allocate(
    stocks: List[Dict[str, Any]],
    total_budget: float,
    max_single: float = 0.30,
    min_score: float = 50.0,
) -> Dict[str, Any]:
    """
    stocks: list of dicts with keys: symbol, fundamental_score, risk_level,
            valuation_status, recommendation
    total_budget: total capital in TWD
    max_single: max weight per stock (0–1)
    min_score: exclude if fundamental < this

    Returns: { allocations: [...], excluded: [...], total_budget }
    """
    excluded = []
    candidates = []

    for s in stocks:
        score = s.get("fundamental_score") or 0
        action = s.get("recommendation")

        if action in EXCLUDE_ACTIONS:
            excluded.append({**s, "exclude_reason": "建議不投入"})
            continue
        if score < min_score:
            excluded.append({**s, "exclude_reason": f"基本面 {score:.0f} < {min_score:.0f}"})
            continue

        risk_m = RISK_MULT.get(s.get("risk_level"), 1.0)
        val_m = VAL_MULT.get(s.get("valuation_status"), 1.0)
        raw = score * risk_m * val_m

        candidates.append({
            **s,
            "risk_mult": risk_m,
            "val_mult": val_m,
            "raw_weight": raw,
        })

    if not candidates:
        return {"allocations": [], "excluded": excluded, "total_budget": total_budget}

    # initial normalize
    total = _norm(candidates)
    for c in candidates:
        c["weight"] = c["raw_weight"] / total

    # iteratively cap at max_single, redistribute excess to uncapped
    for _ in range(20):
        over = [c for c in candidates if c["weight"] > max_single + 1e-9]
        if not over:
            break
        excess = sum(c["weight"] - max_single for c in over)
        for c in over:
            c["weight"] = max_single
            c["capped"] = True
        rest = [c for c in candidates if c["weight"] < max_single - 1e-9]
        if not rest:
            break
        rest_sum = sum(c["weight"] for c in rest)
        if rest_sum <= 0:
            break
        for c in rest:
            c["weight"] += excess * c["weight"] / rest_sum

    # final amount + rationale
    for c in candidates:
        c["amount"] = total_budget * c["weight"]
        bits = [f"基本面 {c.get('fundamental_score', 0):.0f}"]
        if c.get("risk_level"):
            bits.append(f"風險 {c['risk_level']}(×{c['risk_mult']:.1f})")
        if c.get("valuation_status"):
            bits.append(f"估值 {c['valuation_status']}(×{c['val_mult']:.1f})")
        if c.get("capped"):
            bits.append(f"已封頂 {max_single*100:.0f}%")
        c["rationale"] = " · ".join(bits)

    candidates.sort(key=lambda x: -x["weight"])

    return {
        "allocations": candidates,
        "excluded": excluded,
        "total_budget": total_budget,
        "max_single": max_single,
        "min_score": min_score,
    }
