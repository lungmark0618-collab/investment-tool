"""Module C — 估值分析系統"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from utils.data_fetcher import safe_float

STATUS_UNDERVALUED = "明顯低估"
STATUS_FAIR = "合理"
STATUS_OVERVALUED = "高估"
STATUS_OVERHEATED = "過熱"


def _ma200_bias(history: pd.DataFrame) -> Optional[float]:
    if history.empty or len(history) < 200:
        return None
    ma200 = history["Close"].rolling(200).mean().iloc[-1]
    current = history["Close"].iloc[-1]
    if pd.isna(ma200) or ma200 == 0:
        return None
    return float((current - ma200) / ma200 * 100)


def _pe_history_percentile(history: pd.DataFrame, info: dict) -> Optional[float]:
    """Estimate where current PE sits in historical range using price/earnings."""
    trailing_eps = safe_float(info.get("trailingEps"))
    if trailing_eps is None or trailing_eps <= 0 or history.empty:
        return None
    pe_series = history["Close"] / trailing_eps
    pe_series = pe_series[pe_series > 0].dropna()
    if len(pe_series) < 50:
        return None
    current_pe = pe_series.iloc[-1]
    return float((pe_series <= current_pe).mean() * 100)


def calculate(data: Dict[str, Any]) -> Dict[str, Any]:
    info = data["info"]
    history = data.get("history", pd.DataFrame())

    metrics: Dict[str, Dict] = {}

    # PE Ratio
    pe = safe_float(info.get("trailingPE")) or safe_float(info.get("forwardPE"))
    pe_label = "PE(TTM)" if info.get("trailingPE") else "PE(Forward)"
    if pe and pe > 0:
        if pe < 12:
            pe_pts, pe_note = 3, "偏低，可能低估"
        elif pe < 20:
            pe_pts, pe_note = 2, "合理範圍"
        elif pe < 30:
            pe_pts, pe_note = 1, "偏高"
        else:
            pe_pts, pe_note = 0, "過高"
        metrics[pe_label] = {"value": f"{pe:.1f}", "score_pts": pe_pts, "max_pts": 3, "note": pe_note}
    else:
        metrics[pe_label] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "資料不足"}

    # PB Ratio
    pb = safe_float(info.get("priceToBook"))
    if pb and pb > 0:
        if pb < 1.0:
            pb_pts, pb_note = 3, "低於淨值"
        elif pb < 2.5:
            pb_pts, pb_note = 2, "合理"
        elif pb < 5.0:
            pb_pts, pb_note = 1, "偏高"
        else:
            pb_pts, pb_note = 0, "過高"
        metrics["PB(股價淨值比)"] = {"value": f"{pb:.2f}", "score_pts": pb_pts, "max_pts": 3, "note": pb_note}
    else:
        metrics["PB(股價淨值比)"] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "資料不足"}

    # Dividend Yield
    dy = safe_float(info.get("dividendYield")) or safe_float(info.get("yield"))
    if dy and dy > 0:
        if dy > 0.05:
            dy_pts, dy_note = 3, f"殖利率 {dy*100:.2f}% 高"
        elif dy > 0.03:
            dy_pts, dy_note = 2, f"殖利率 {dy*100:.2f}% 合理"
        elif dy > 0.01:
            dy_pts, dy_note = 1, f"殖利率 {dy*100:.2f}% 偏低"
        else:
            dy_pts, dy_note = 0, f"殖利率 {dy*100:.2f}% 極低"
        metrics["股息殖利率"] = {"value": f"{dy*100:.2f}%", "score_pts": dy_pts, "max_pts": 3, "note": dy_note}
    else:
        metrics["股息殖利率"] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "無配息"}

    # PE Historical percentile
    pe_pct = _pe_history_percentile(history, info)
    if pe_pct is not None:
        if pe_pct < 30:
            ppct_pts, ppct_note = 3, f"PE歷史低位 ({pe_pct:.0f}%ile)"
        elif pe_pct < 60:
            ppct_pts, ppct_note = 2, f"PE歷史中位 ({pe_pct:.0f}%ile)"
        elif pe_pct < 80:
            ppct_pts, ppct_note = 1, f"PE歷史高位 ({pe_pct:.0f}%ile)"
        else:
            ppct_pts, ppct_note = 0, f"PE歷史極高 ({pe_pct:.0f}%ile)"
        metrics["PE歷史分位"] = {"value": f"{pe_pct:.0f}%ile", "score_pts": ppct_pts, "max_pts": 3, "note": ppct_note}
    else:
        metrics["PE歷史分位"] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "資料不足"}

    # 52-week position
    high52 = safe_float(info.get("fiftyTwoWeekHigh"))
    low52 = safe_float(info.get("fiftyTwoWeekLow"))
    current = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice")) or safe_float(info.get("previousClose"))
    if high52 and low52 and current and (high52 - low52) > 0:
        pos = (current - low52) / (high52 - low52) * 100
        if pos < 25:
            pos_pts, pos_note = 3, f"接近52週低點 ({pos:.0f}%)"
        elif pos < 50:
            pos_pts, pos_note = 2, f"中低區間 ({pos:.0f}%)"
        elif pos < 75:
            pos_pts, pos_note = 1, f"中高區間 ({pos:.0f}%)"
        else:
            pos_pts, pos_note = 0, f"接近52週高點 ({pos:.0f}%)"
        metrics["52週位置"] = {"value": f"{pos:.0f}%", "score_pts": pos_pts, "max_pts": 3, "note": pos_note}
    else:
        metrics["52週位置"] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "資料不足"}

    # MA200 Bias
    bias = _ma200_bias(history)
    if bias is not None:
        if bias < -15:
            bias_pts, bias_note = 3, f"低於MA200 {abs(bias):.1f}% — 可能低估"
        elif bias < 5:
            bias_pts, bias_note = 2, f"均線附近 ({bias:+.1f}%)"
        elif bias < 15:
            bias_pts, bias_note = 1, f"高於MA200 {bias:.1f}%"
        else:
            bias_pts, bias_note = 0, f"高於MA200 {bias:.1f}% — 過熱警示"
        metrics["均線乖離率(MA200)"] = {"value": f"{bias:+.1f}%", "score_pts": bias_pts, "max_pts": 3, "note": bias_note}
    else:
        metrics["均線乖離率(MA200)"] = {"value": "N/A", "score_pts": 1, "max_pts": 3, "note": "歷史資料不足"}

    total_pts = sum(m["score_pts"] for m in metrics.values())
    max_pts = sum(m["max_pts"] for m in metrics.values())
    ratio = total_pts / max_pts if max_pts > 0 else 0.5

    if ratio >= 0.75:
        status, color, suggestion = STATUS_UNDERVALUED, "green", "適合加碼"
    elif ratio >= 0.50:
        status, color, suggestion = STATUS_FAIR, "blue", "正常投入"
    elif ratio >= 0.30:
        status, color, suggestion = STATUS_OVERVALUED, "orange", "降低投入比例"
    else:
        status, color, suggestion = STATUS_OVERHEATED, "red", "保留現金，等待回調"

    return {
        "status": status,
        "color": color,
        "suggestion": suggestion,
        "metrics": metrics,
        "valuation_score": round(ratio * 100, 1),
        "ma200_bias": bias,
    }
