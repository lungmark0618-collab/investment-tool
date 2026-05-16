"""股票名稱搜尋 — 支援英文名 / 代碼 / 部分台股中文名稱對應

排序策略:
  1. 完全相符的 ticker (AAPL = AAPL) → 100 分
  2. 開頭相符 (AAPL → AAPLW) → 50 分
  3. 包含 query (AAPL 在 AAPL.MX 內) → 25 分
  4. 名稱包含 query (AAPL 在 "Apple Inc" 內) → 10 分

這樣輸入 AAPL 時,真正的 AAPL 會排在 AAPU/AAPB 等槓桿 ETF 前面。
"""
from typing import List, Dict
import yfinance as yf

# 台股常見公司中文名 → 代碼 fallback（yfinance 中文搜尋不穩）
TW_NAME_ALIAS = {
    "台積電": "2330.TW", "台積": "2330.TW", "tsmc": "2330.TW",
    "聯發科": "2454.TW", "鴻海": "2317.TW", "富邦金": "2881.TW",
    "國泰金": "2882.TW", "中信金": "2891.TW", "兆豐金": "2886.TW",
    "玉山金": "2884.TW", "元大金": "2885.TW", "第一金": "2892.TW",
    "華南金": "2880.TW", "永豐金": "2890.TW", "合庫金": "5880.TW",
    "中華電": "2412.TW", "台達電": "2308.TW", "聯電": "2303.TW",
    "南亞": "1303.TW", "台塑": "1301.TW", "台化": "1326.TW",
    "中鋼": "2002.TW", "長榮": "2603.TW", "陽明": "2609.TW",
    "華航": "2610.TW", "長榮航": "2618.TW",
    "和泰車": "2207.TW", "裕隆": "2201.TW",
    "統一": "1216.TW", "大立光": "3008.TW",
    # ETF
    "元大台灣50": "0050.TW", "0050": "0050.TW",
    "高股息": "0056.TW", "元大高股息": "0056.TW",
    "00878": "00878.TW", "國泰永續": "00878.TW",
    "00919": "00919.TW", "群益台灣精選高息": "00919.TW",
    "00929": "00929.TW", "復華台灣科技優息": "00929.TW",
    "00940": "00940.TW", "元大臺灣價值高息": "00940.TW",
}


def _score(symbol: str, name: str, q_upper: str, q_lower: str) -> int:
    """排序分數,越高越靠前。"""
    sym_upper = symbol.upper()
    sym_base = sym_upper.split(".")[0]  # AAPL.TW → AAPL
    name_lower = (name or "").lower()

    # 完全相符優先(同時考慮帶/不帶後綴的形式)
    if sym_base == q_upper or sym_upper == q_upper:
        return 100
    # 加上 .TW 也算完全相符 (2330 ↔ 2330.TW)
    if sym_upper == f"{q_upper}.TW" or sym_upper == f"{q_upper}.TWO":
        return 100
    # 開頭相符
    if sym_base.startswith(q_upper):
        return 50
    # 包含於代碼
    if q_upper in sym_base:
        return 25
    # 包含於名稱
    if q_lower and q_lower in name_lower:
        return 10
    return 0


def search_stocks(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """
    搜尋股票,回傳:[{symbol, name, exchange}, ...]
    支援:英文名、ticker 代碼、純數字(自動補 .TW)、部分中文公司名
    """
    q = query.strip()
    if not q:
        return []

    q_upper = q.upper()
    q_lower = q.lower()
    seen = set()
    candidates: List[Dict[str, str]] = []

    def add(sym: str, name: str, exch: str = ""):
        if sym and sym.upper() not in seen:
            seen.add(sym.upper())
            candidates.append({"symbol": sym, "name": name or sym, "exchange": exch})

    # 1) 台股中文名/別名 fallback
    for alias, sym in TW_NAME_ALIAS.items():
        if alias.lower() == q_lower or q_lower in alias.lower():
            add(sym, alias, "TAI")

    # 2) yfinance Search(英文 / 代碼) — 多抓一些,後面排序篩
    try:
        s = yf.Search(q, max_results=limit * 3)
        for quote in s.quotes[: limit * 3]:
            sym = quote.get("symbol", "")
            name = quote.get("shortname") or quote.get("longname") or sym
            exch = quote.get("exchange", "")
            if sym:
                add(sym, name, exch)
    except Exception:
        pass

    # 3) 純數字 → 補 .TW 推測(可能 yfinance 沒給,但用戶想看)
    if q.isdigit() and 4 <= len(q) <= 6:
        sym = f"{q}.TW"
        if sym.upper() not in seen:
            add(sym, f"台股 {q}", "TAI")

    # 4) 英數字 query → 也補一個 raw ticker 推測,確保 AAPL 一定會出現
    if q_upper.isalpha() and 1 <= len(q_upper) <= 5 and q_upper not in seen:
        # 直接加入推測項;yfinance 可能已經有了但有可能漏掉
        add(q_upper, q_upper, "")

    # 5) 排序:完全相符 > 開頭相符 > 包含 > 名稱包含
    candidates.sort(
        key=lambda r: _score(r["symbol"], r["name"], q_upper, q_lower),
        reverse=True,
    )

    return candidates[:limit]
