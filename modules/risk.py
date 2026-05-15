"""Module B — 風險評估系統"""
import numpy as np
import pandas as pd
from typing import Dict, Any
from utils.data_fetcher import safe_float

LEVEL_CONSERVATIVE = "保守型"
LEVEL_NEUTRAL = "中性型"
LEVEL_HIGH = "高風險型"


def _annualized_volatility(history: pd.DataFrame) -> float | None:
    if history.empty or len(history) < 20:
        return None
    returns = history["Close"].pct_change().dropna()
    return float(returns.std() * np.sqrt(252))


def _max_drawdown(history: pd.DataFrame) -> float | None:
    if history.empty:
        return None
    prices = history["Close"]
    rolling_max = prices.cummax()
    drawdown = (prices - rolling_max) / rolling_max
    return float(drawdown.min())


def _revenue_volatility(income_stmt: pd.DataFrame) -> float | None:
    try:
        row = next((r for r in ["Total Revenue", "Revenue"] if r in income_stmt.index), None)
        if not row:
            return None
        vals = income_stmt.loc[row].dropna()
        if len(vals) < 2:
            return None
        growths = vals.pct_change(-1).dropna()
        return float(growths.std())
    except Exception:
        return None


CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Consumer Cyclical", "Real Estate"}
DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare"}


def calculate(data: Dict[str, Any]) -> Dict[str, Any]:
    info = data["info"]
    history = data.get("history", pd.DataFrame())
    income_stmt = data.get("income_stmt", pd.DataFrame())
    is_etf = data.get("is_etf", False)

    metrics = {}

    # Volatility
    vol = _annualized_volatility(history)
    metrics["波動率(年化)"] = {
        "value": f"{vol*100:.1f}%" if vol else "N/A",
        "risk_pts": 0 if vol is None else (1 if vol < 0.15 else 2 if vol < 0.25 else 3 if vol < 0.40 else 4),
        "note": ("低波動" if vol and vol < 0.15 else "中波動" if vol and vol < 0.25 else "高波動" if vol else "N/A"),
    }

    # Max drawdown
    mdd = _max_drawdown(history)
    metrics["最大回撤"] = {
        "value": f"{mdd*100:.1f}%" if mdd else "N/A",
        "risk_pts": 0 if mdd is None else (1 if mdd > -0.20 else 2 if mdd > -0.35 else 3 if mdd > -0.50 else 4),
        "note": ("抗跌佳" if mdd and mdd > -0.20 else "中等" if mdd and mdd > -0.35 else "高回撤" if mdd else "N/A"),
    }

    # Beta
    beta = safe_float(info.get("beta"))
    metrics["Beta"] = {
        "value": f"{beta:.2f}" if beta else "N/A",
        "risk_pts": 0 if beta is None else (0 if beta < 0.8 else 1 if beta < 1.1 else 2 if beta < 1.5 else 3),
        "note": ("低市場相關" if beta and beta < 0.8 else "與市場同步" if beta and beta < 1.1 else "高市場敏感" if beta else "N/A"),
    }

    # Sector cyclicality
    sector = info.get("sector", "")
    if sector in CYCLICAL_SECTORS:
        sector_pts, sector_note = 3, f"{sector} — 景氣循環"
    elif sector in DEFENSIVE_SECTORS:
        sector_pts, sector_note = 0, f"{sector} — 防禦性"
    elif sector:
        sector_pts, sector_note = 1, f"{sector} — 中性"
    else:
        sector_pts, sector_note = 1, "產業不明"

    metrics["產業循環性"] = {
        "value": sector or "N/A",
        "risk_pts": sector_pts,
        "note": sector_note,
    }

    # Revenue volatility
    if not is_etf:
        rev_vol = _revenue_volatility(income_stmt)
        metrics["營收波動"] = {
            "value": f"{rev_vol*100:.1f}%" if rev_vol else "N/A",
            "risk_pts": 0 if rev_vol is None else (0 if rev_vol < 0.05 else 1 if rev_vol < 0.15 else 2 if rev_vol < 0.30 else 3),
            "note": ("穩定" if rev_vol and rev_vol < 0.05 else "中等波動" if rev_vol and rev_vol < 0.15 else "高波動" if rev_vol else "N/A"),
        }
    else:
        metrics["營收波動"] = {"value": "ETF不適用", "risk_pts": 0, "note": "分散持股"}

    total_risk_pts = sum(m["risk_pts"] for m in metrics.values())
    max_pts = 4 + 4 + 3 + 3 + 3  # sum of each metric's max

    ratio = total_risk_pts / max_pts if max_pts > 0 else 0

    if ratio < 0.35:
        level = LEVEL_CONSERVATIVE
        color = "green"
        desc = "波動低，適合保守型投資人"
    elif ratio < 0.65:
        level = LEVEL_NEUTRAL
        color = "blue"
        desc = "波動中等，適合一般長期投資"
    else:
        level = LEVEL_HIGH
        color = "red"
        desc = "波動高，需配置較小比例"

    return {
        "level": level,
        "color": color,
        "description": desc,
        "metrics": metrics,
        "risk_score": round(ratio * 100, 1),
    }
