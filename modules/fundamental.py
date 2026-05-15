"""Module A — 基本面評分系統 (0-100分)"""
import pandas as pd
from typing import Dict, Tuple, Any
from utils.data_fetcher import safe_float

# (score, max_score, description)
ScoreItem = Tuple[float, float, str]


def _score_revenue_growth(info: dict, income_stmt: pd.DataFrame) -> ScoreItem:
    try:
        if not income_stmt.empty:
            row = next((r for r in ["Total Revenue", "Revenue"] if r in income_stmt.index), None)
            if row:
                vals = income_stmt.loc[row].dropna()
                if len(vals) >= 2:
                    growths = vals.pct_change(-1).dropna()
                    pos = int((growths > 0).sum())
                    n = len(growths)
                    if pos >= 3:
                        return 10.0, 10.0, f"近{n}年中{pos}年營收成長"
                    elif pos >= 2:
                        return 7.0, 10.0, f"近{n}年中{pos}年營收成長"
                    elif pos >= 1:
                        return 4.0, 10.0, f"近{n}年中{pos}年營收成長"
                    else:
                        return 1.0, 10.0, "營收持續衰退"
    except Exception:
        pass

    g = safe_float(info.get("revenueGrowth"))
    if g is not None:
        if g > 0.15:
            return 10.0, 10.0, f"營收成長 {g*100:.1f}%"
        elif g > 0.08:
            return 8.0, 10.0, f"營收成長 {g*100:.1f}%"
        elif g > 0.03:
            return 6.0, 10.0, f"營收成長 {g*100:.1f}%"
        elif g > 0:
            return 4.0, 10.0, f"營收微幅成長 {g*100:.1f}%"
        else:
            return 1.0, 10.0, f"營收衰退 {g*100:.1f}%"
    return 5.0, 10.0, "資料不足"


def _score_eps_growth(info: dict, income_stmt: pd.DataFrame) -> ScoreItem:
    try:
        if not income_stmt.empty:
            row = next((r for r in ["Diluted EPS", "Basic EPS"] if r in income_stmt.index), None)
            if row:
                vals = income_stmt.loc[row].dropna()
                if len(vals) >= 2:
                    growths = vals.pct_change(-1).dropna()
                    pos = int((growths > 0).sum())
                    n = len(growths)
                    if pos >= 3:
                        return 10.0, 10.0, f"EPS近{n}年中{pos}年成長"
                    elif pos >= 2:
                        return 7.0, 10.0, f"EPS{pos}年成長"
                    elif pos >= 1:
                        return 4.0, 10.0, f"EPS{pos}年成長"
                    else:
                        return 1.0, 10.0, "EPS持續衰退"
    except Exception:
        pass

    g = safe_float(info.get("earningsGrowth"))
    if g is not None:
        if g > 0.15:
            return 10.0, 10.0, f"盈利成長 {g*100:.1f}%"
        elif g > 0.08:
            return 8.0, 10.0, f"盈利成長 {g*100:.1f}%"
        elif g > 0:
            return 5.0, 10.0, f"盈利微幅成長 {g*100:.1f}%"
        else:
            return 1.0, 10.0, f"盈利衰退 {g*100:.1f}%"
    return 5.0, 10.0, "資料不足"


def _score_fcf(info: dict, cashflow: pd.DataFrame) -> ScoreItem:
    try:
        if not cashflow.empty:
            fcf_row = next((r for r in ["Free Cash Flow"] if r in cashflow.index), None)
            ocf_row = next((r for r in ["Operating Cash Flow", "Total Cash From Operating Activities"] if r in cashflow.index), None)
            capex_row = next((r for r in ["Capital Expenditure", "Capital Expenditures"] if r in cashflow.index), None)

            if fcf_row:
                vals = cashflow.loc[fcf_row].dropna()
            elif ocf_row and capex_row:
                vals = (cashflow.loc[ocf_row] + cashflow.loc[capex_row]).dropna()
            elif ocf_row:
                vals = cashflow.loc[ocf_row].dropna()
            else:
                vals = pd.Series(dtype=float)

            if len(vals) >= 1:
                pos = int((vals > 0).sum())
                n = len(vals)
                if pos == n and n >= 3:
                    return 10.0, 10.0, f"自由現金流{n}年持續為正"
                elif pos >= n * 0.7:
                    return 7.0, 10.0, f"FCF {pos}/{n}年為正"
                elif pos >= 1:
                    return 4.0, 10.0, "FCF不穩定"
                else:
                    return 1.0, 10.0, "自由現金流持續為負"
    except Exception:
        pass

    fcf = safe_float(info.get("freeCashflow"))
    mc = safe_float(info.get("marketCap"))
    if fcf is not None and mc and mc > 0:
        y = fcf / mc
        if y > 0.05:
            return 10.0, 10.0, f"FCF殖利率 {y*100:.1f}% 優秀"
        elif y > 0.02:
            return 7.0, 10.0, f"FCF殖利率 {y*100:.1f}%"
        elif y > 0:
            return 5.0, 10.0, f"FCF殖利率 {y*100:.1f}%"
        else:
            return 1.0, 10.0, "自由現金流為負"
    return 5.0, 10.0, "資料不足"


def _score_roe(info: dict) -> ScoreItem:
    roe = safe_float(info.get("returnOnEquity"))
    if roe is not None:
        if roe > 0.20:
            return 10.0, 10.0, f"ROE {roe*100:.1f}% 優秀"
        elif roe > 0.15:
            return 8.0, 10.0, f"ROE {roe*100:.1f}% 良好"
        elif roe > 0.10:
            return 6.0, 10.0, f"ROE {roe*100:.1f}% 尚可"
        elif roe > 0.05:
            return 3.0, 10.0, f"ROE {roe*100:.1f}% 偏低"
        else:
            return 1.0, 10.0, f"ROE {roe*100:.1f}% 不佳"
    return 5.0, 10.0, "資料不足"


def _score_debt(info: dict) -> ScoreItem:
    de = safe_float(info.get("debtToEquity"))
    if de is not None:
        # yfinance sometimes gives this as percentage (e.g. 50 = 50%)
        if de > 10:
            de = de / 100
        if de < 0.3:
            return 10.0, 10.0, f"D/E {de*100:.0f}% 極低"
        elif de < 0.6:
            return 8.0, 10.0, f"D/E {de*100:.0f}% 低"
        elif de < 1.0:
            return 5.0, 10.0, f"D/E {de*100:.0f}% 中等"
        elif de < 2.0:
            return 3.0, 10.0, f"D/E {de*100:.0f}% 偏高"
        else:
            return 1.0, 10.0, f"D/E {de*100:.0f}% 過高"
    return 5.0, 10.0, "資料不足"


def _score_gross_margin(info: dict) -> ScoreItem:
    gm = safe_float(info.get("grossMargins"))
    if gm is not None:
        if gm > 0.50:
            return 10.0, 10.0, f"毛利率 {gm*100:.1f}% 優秀"
        elif gm > 0.35:
            return 8.0, 10.0, f"毛利率 {gm*100:.1f}% 良好"
        elif gm > 0.20:
            return 6.0, 10.0, f"毛利率 {gm*100:.1f}% 尚可"
        elif gm > 0.10:
            return 3.0, 10.0, f"毛利率 {gm*100:.1f}% 偏低"
        else:
            return 1.0, 10.0, f"毛利率 {gm*100:.1f}% 不佳"
    return 5.0, 10.0, "資料不足"


def _score_operating_margin(info: dict) -> ScoreItem:
    om = safe_float(info.get("operatingMargins"))
    if om is not None:
        if om > 0.25:
            return 10.0, 10.0, f"營益率 {om*100:.1f}% 優秀"
        elif om > 0.15:
            return 8.0, 10.0, f"營益率 {om*100:.1f}% 良好"
        elif om > 0.08:
            return 6.0, 10.0, f"營益率 {om*100:.1f}% 尚可"
        elif om > 0.03:
            return 3.0, 10.0, f"營益率 {om*100:.1f}% 偏低"
        else:
            return 1.0, 10.0, f"營益率 {om*100:.1f}% 不佳"
    return 5.0, 10.0, "資料不足"


def _score_dividend(info: dict) -> ScoreItem:
    div_yield = safe_float(info.get("dividendYield"))
    five_yr = safe_float(info.get("fiveYearAvgDividendYield"))

    if five_yr and five_yr > 0:
        label = f"5年均殖利率 {five_yr:.2f}%"
        if div_yield and div_yield > 0:
            label += f"，當前 {div_yield*100:.2f}%"
        return 10.0, 10.0, label

    if div_yield and div_yield > 0:
        return 7.0, 10.0, f"股息殖利率 {div_yield*100:.2f}%"

    payout = safe_float(info.get("payoutRatio"))
    if payout and payout > 0:
        return 5.0, 10.0, f"配息率 {payout*100:.1f}%（無歷史紀錄）"

    return 2.0, 10.0, "無股息（成長型可接受）"


def _score_market_cap(info: dict) -> ScoreItem:
    mc = safe_float(info.get("marketCap"))
    if mc:
        if mc > 1e12:
            return 10.0, 10.0, f"市值 {mc/1e12:.1f}T — 超大型"
        elif mc > 1e11:
            return 9.0, 10.0, f"市值 {mc/1e9:.0f}B — 大型"
        elif mc > 1e10:
            return 7.0, 10.0, f"市值 {mc/1e9:.1f}B — 中大型"
        elif mc > 1e9:
            return 5.0, 10.0, f"市值 {mc/1e9:.2f}B — 中型"
        elif mc > 1e8:
            return 3.0, 10.0, f"市值 {mc/1e6:.0f}M — 小型"
        else:
            return 1.0, 10.0, f"市值 {mc/1e6:.0f}M — 微型"
    return 5.0, 10.0, "資料不足"


def _score_industry(info: dict) -> ScoreItem:
    sector = info.get("sector", "")
    mc = safe_float(info.get("marketCap"), 0)

    strong = {"Technology", "Consumer Defensive", "Healthcare", "Financial Services", "Communication Services"}
    moderate = {"Industrials", "Utilities"}
    cyclical = {"Energy", "Basic Materials", "Consumer Cyclical", "Real Estate"}

    base = 8.0 if mc > 1e11 else 6.0 if mc > 1e10 else 4.0

    if sector in strong:
        return min(10.0, base + 2.0), 10.0, f"{sector} — 護城河強"
    elif sector in moderate:
        return base, 10.0, f"{sector} — 護城河中等"
    elif sector in cyclical:
        return max(2.0, base - 2.0), 10.0, f"{sector} — 景氣循環產業"
    elif sector:
        return base, 10.0, f"{sector}"
    return 5.0, 10.0, "資料不足"


def _score_etf(info: dict) -> Dict[str, Any]:
    """Simplified scoring for ETFs."""
    expense = safe_float(info.get("annualReportExpenseRatio")) or safe_float(info.get("totalExpenseRatio"))
    yield_val = safe_float(info.get("yield")) or safe_float(info.get("dividendYield"))
    ytd = safe_float(info.get("ytdReturn"))
    three_yr = safe_float(info.get("threeYearAverageReturn"))
    five_yr = safe_float(info.get("fiveYearAverageReturn"))

    score = 70.0  # ETFs default to decent score
    details_text = []

    if expense is not None:
        if expense < 0.002:
            score += 10
            details_text.append(f"費用率 {expense*100:.2f}% 極低")
        elif expense < 0.005:
            score += 5
            details_text.append(f"費用率 {expense*100:.2f}% 低")
        else:
            score -= 5
            details_text.append(f"費用率 {expense*100:.2f}% 偏高")

    if five_yr and five_yr > 0.08:
        score += 10
        details_text.append(f"5年年化報酬 {five_yr*100:.1f}%")
    elif five_yr and five_yr > 0.05:
        score += 5
        details_text.append(f"5年年化報酬 {five_yr*100:.1f}%")

    score = max(0.0, min(100.0, score))

    if score >= 85:
        grade, color = "優質長期標的", "green"
    elif score >= 70:
        grade, color = "可長期觀察", "blue"
    else:
        grade, color = "風險偏高", "orange"

    return {
        "total_score": round(score, 1),
        "grade": grade,
        "color": color,
        "details": {k: (score / 10, 10.0, k) for k in ["ETF整體評估"]},
        "is_etf": True,
        "etf_summary": "，".join(details_text) or "指數型ETF",
    }


def calculate(data: Dict[str, Any]) -> Dict[str, Any]:
    info = data["info"]
    is_etf = data.get("is_etf", False)

    if is_etf:
        return _score_etf(info)

    income_stmt = data.get("income_stmt", pd.DataFrame())
    balance_sheet = data.get("balance_sheet", pd.DataFrame())
    cashflow = data.get("cashflow", pd.DataFrame())

    items: Dict[str, ScoreItem] = {
        "營收成長": _score_revenue_growth(info, income_stmt),
        "EPS成長": _score_eps_growth(info, income_stmt),
        "自由現金流": _score_fcf(info, cashflow),
        "ROE": _score_roe(info),
        "負債比": _score_debt(info),
        "毛利率": _score_gross_margin(info),
        "營益率": _score_operating_margin(info),
        "股利紀錄": _score_dividend(info),
        "市值規模": _score_market_cap(info),
        "產業地位": _score_industry(info),
    }

    total = sum(s[0] for s in items.values())
    max_total = sum(s[1] for s in items.values())
    score = round((total / max_total) * 100, 1) if max_total > 0 else 50.0

    if score >= 85:
        grade, color = "優質長期標的", "green"
    elif score >= 70:
        grade, color = "可長期觀察", "blue"
    elif score >= 50:
        grade, color = "風險偏高", "orange"
    else:
        grade, color = "不建議長投", "red"

    return {
        "total_score": score,
        "grade": grade,
        "color": color,
        "details": items,
        "is_etf": False,
    }
