"""長期投資決策工具 — Streamlit App"""
import platform
import sys
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

# Ensure local modules are importable when running `streamlit run app.py`
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from utils.data_fetcher import fetch_ticker, get_all_data, safe_float, get_fx_rate
from utils.search import search_stocks
from utils import glossary
from utils.notifier import (
    send, build_message,
    get_topic, set_topic, get_server, set_server,
    get_scan_times, set_scan_times,
    get_dedup_hours, set_dedup_hours,
    get_signal_filter, set_signal_filter,
)
from utils import scheduler
from modules import fundamental, risk, valuation, allocation, position, portfolio, market_regime
from database.db import (
    save_analysis, get_history,
    add_to_watchlist, get_watchlist, remove_from_watchlist,
    add_transaction, get_transactions, delete_transaction, update_transaction,
    get_holdings, get_avg_cost,
)

# ─────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="長期投資決策工具",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def score_gauge(score: float, title: str, max_val: float = 100) -> go.Figure:
    color = "#2ecc71" if score >= 70 else "#3498db" if score >= 50 else "#e74c3c"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": title, "font": {"size": 14}},
        gauge={
            "axis": {
                "range": [0, max_val],
                "tickmode": "array",
                "tickvals": [0, 25, 50, 75, 100],
                "tickfont": {"size": 10},
            },
            "bar": {"color": color},
            "steps": [
                {"range": [0, 50], "color": "#2d0e0e"},
                {"range": [50, 70], "color": "#2d1f0e"},
                {"range": [70, 85], "color": "#0e2d1a"},
                {"range": [85, 100], "color": "#0a2b18"},
            ],
            "threshold": {"line": {"color": "white", "width": 2}, "thickness": 0.75, "value": score},
        },
    ))
    fig.update_layout(height=210, margin=dict(l=30, r=30, t=40, b=0))
    return fig


def price_chart(history: pd.DataFrame, symbol: str) -> go.Figure:
    if history.empty:
        return go.Figure()

    fig = go.Figure()

    # Candlestick (last 1 year)
    recent = history.tail(252)
    fig.add_trace(go.Scatter(
        x=recent.index, y=recent["Close"],
        name="收盤價", line=dict(color="#3498db", width=1.5),
    ))

    # MA50
    ma50 = history["Close"].rolling(50).mean().tail(252)
    fig.add_trace(go.Scatter(
        x=ma50.index, y=ma50,
        name="MA50", line=dict(color="#f39c12", width=1, dash="dot"),
    ))

    # MA200
    if len(history) >= 200:
        ma200 = history["Close"].rolling(200).mean().tail(252)
        fig.add_trace(go.Scatter(
            x=ma200.index, y=ma200,
            name="MA200", line=dict(color="#e74c3c", width=1.5, dash="dash"),
        ))

    fig.update_layout(
        title=dict(text=f"{symbol} 近1年價格走勢", x=0, xanchor="left", font=dict(size=14)),
        xaxis_title="日期",
        yaxis_title="價格",
        height=370,
        margin=dict(l=20, r=20, t=40, b=50),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="white"),
    )
    return fig


def fundamental_bar(details: dict) -> go.Figure:
    labels = list(details.keys())
    scores = [v[0] for v in details.values()]
    max_scores = [v[1] for v in details.values()]
    colors = ["#2ecc71" if s / m >= 0.7 else "#f39c12" if s / m >= 0.4 else "#e74c3c"
              for s, m in zip(scores, max_scores)]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=max_scores, name="滿分", marker_color="#2d3748", opacity=0.5,
    ))
    fig.add_trace(go.Bar(
        x=labels, y=scores, name="得分", marker_color=colors,
    ))
    fig.update_layout(
        barmode="overlay",
        height=280,
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="white"),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
    )
    return fig


def allocation_pie(invest_ratio: float, cash_ratio: float) -> go.Figure:
    fig = go.Figure(go.Pie(
        labels=["本月投入", "保留現金"],
        values=[invest_ratio, max(0, cash_ratio)],
        hole=0.5,
        marker_colors=["#2ecc71", "#95a5a6"],
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="#0e1117",
        font=dict(color="white"),
        showlegend=True,
        legend=dict(orientation="h"),
    )
    return fig


# ─────────────────────────────────────────────
# Session state init
# ─────────────────────────────────────────────
if "auto_analyze" not in st.session_state:
    st.session_state["auto_analyze"] = False
if "mode" not in st.session_state:
    st.session_state["mode"] = "單檔分析"


@st.dialog("📚 投資指標完整說明", width="large")
def _show_glossary_dialog():
    st.caption("這是工具用到的所有指標、公式、判讀標準，分類整理供你隨時查閱")
    _section_titles = [t for t, _ in glossary.ALL_SECTIONS]
    _tabs = st.tabs(_section_titles)
    for _tab, (_title, _body) in zip(_tabs, glossary.ALL_SECTIONS):
        with _tab:
            st.markdown(_body)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_market_regime() -> dict:
    return market_regime.analyze()


@st.cache_data(ttl=600, show_spinner=False)
def _cached_fetch(symbol: str):
    """抓取 + 整理單檔資料，快取 10 分鐘。回傳 (used_symbol, data) 或 (None, None)。
    包成 cache 後，同一檔在分析頁的任何 rerun（記錄交易、改設定…）都直接命中，
    不再每次重打 yfinance 抓 5 年歷史 + 三張財報，也避免重複寫入 analysis_history。"""
    tk, used = fetch_ticker(symbol)
    if tk is None:
        return None, None
    return used, get_all_data(tk)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_fx(from_ccy: str, to_ccy: str):
    """匯率快取，避免每次 rerun / 每筆外幣明細都打一次 yfinance。"""
    return get_fx_rate(from_ccy, to_ccy)


@st.cache_data(ttl=3, show_spinner=False)
def _cached_quote(symbol: str):
    """即時報價（持倉卡片與投資組合總覽共用）。TTL 短以配合自動更新 fragment。"""
    try:
        tk, _ = fetch_ticker(symbol)
        if not tk:
            return None
        info = tk.info or {}
        return {
            "cur_price": (info.get("currentPrice") or info.get("regularMarketPrice")
                          or info.get("previousClose")),
            "name": info.get("longName") or info.get("shortName") or symbol,
            "currency": info.get("currency", ""),
        }
    except Exception:
        return None


def _classify_market(symbol: str, currency: str = None) -> str:
    """依代碼/幣別粗分 台股 / 美股 / 其他（帳務與總覽共用）。"""
    s = (symbol or "").upper()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return "台股"
    if currency == "TWD":
        return "台股"
    # 純數字（4-6 碼）= 台股代號（即使存檔時沒加 .TW）
    if s.isdigit() and 4 <= len(s) <= 6:
        return "台股"
    if currency == "USD" or s.isalpha():
        return "美股"
    return "其他"


def _holding_value_twd(h: dict, cur_price):
    """單一持倉的台幣現值與損益。與帳務卡片同一套公式（匯率以成本內含值近似）。
    回傳 (cur_value_twd, pnl_twd, pnl_pct)。"""
    if cur_price and h.get("avg_cost"):
        pnl_pct = (cur_price - h["avg_cost"]) / h["avg_cost"] * 100
        cur_value_twd = (cur_price / h["avg_cost"]) * h["twd_cost"]
        return cur_value_twd, cur_value_twd - h["twd_cost"], pnl_pct
    return h["twd_cost"], 0.0, 0.0


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_index_history(symbol: str, period: str = "1y"):
    """Fetch index history for chart rendering. Returns dict with close/ma50/ma200/dates."""
    import yfinance as yf
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            return None
        return {
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "close": hist["Close"].tolist(),
            "ma50": hist["Close"].rolling(50).mean().tolist(),
            "ma200": hist["Close"].rolling(200).mean().tolist(),
        }
    except Exception:
        return None


def _index_chart(data: dict, title: str, color: str = "#3498db") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["dates"], y=data["close"],
        name="收盤", line=dict(color=color, width=2),
    ))
    fig.add_trace(go.Scatter(
        x=data["dates"], y=data["ma50"],
        name="MA50", line=dict(color="#f39c12", width=1, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=data["dates"], y=data["ma200"],
        name="MA200", line=dict(color="#e74c3c", width=1.5, dash="dash"),
    ))
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=14)),
        height=280,
        margin=dict(l=40, r=20, t=40, b=30),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        hovermode="x unified",
    )
    return fig


def _render_market_charts():
    """大盤走勢圖：S&P 500 + 台股加權，並列顯示。"""
    spx = _cached_index_history("^GSPC")
    twii = _cached_index_history("^TWII")

    if not spx and not twii:
        return

    col_us, col_tw = st.columns(2)
    with col_us:
        if spx:
            st.plotly_chart(_index_chart(spx, "🇺🇸 S&P 500（近一年）", "#3498db"),
                            width="stretch")
        else:
            st.caption("無法取得 S&P 500 資料")
    with col_tw:
        if twii:
            st.plotly_chart(_index_chart(twii, "🇹🇼 台股加權（近一年）", "#2ecc71"),
                            width="stretch")
        else:
            st.caption("無法取得台股加權資料")


def _render_market_banner(compact: bool = True):
    """頂部市場狀態 banner — 所有模式共用。"""
    regime = _cached_market_regime()
    if not regime.get("available"):
        return
    color = regime["color"]
    vix = regime["vix"]
    spx_bias = regime["spx"]["bias_ma200_pct"]
    mult = regime["budget_multiplier"]
    label = regime["regime"]
    desc = regime["description"]

    cols = st.columns([1.2, 1, 1, 2])
    with cols[0]:
        st.markdown(
            f"<div style='background:{color};color:white;padding:10px 14px;"
            f"border-radius:10px;text-align:center;font-weight:700;font-size:1.1rem'>"
            f"市場狀態：{label}</div>",
            unsafe_allow_html=True,
        )
    cols[1].metric("VIX", f"{vix:.1f}", help="< 20 平靜 / 20–28 不安 / > 28 恐慌")
    cols[2].metric("SPX vs MA200", f"{spx_bias:+.1f}%")
    cols[3].metric("資金乘數", f"×{mult:.2f}", help=desc)

# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
with st.sidebar:
    st.title("📈 長期投資決策工具")
    st.caption("基本面 × 估值 × 資金管理")

    _modes = [
        ("單檔分析", "📊"),
        ("多標配置", "🎯"),
        ("帳務", "📒"),
        ("總覽", "💼"),
    ]
    for _name, _icon in _modes:
        _is_active = st.session_state["mode"] == _name
        if st.button(
            f"{_icon}  {_name}",
            key=f"mode_btn_{_name}",
            width="stretch",
            type="primary" if _is_active else "secondary",
        ):
            st.session_state["mode"] = _name
            st.rerun()
    mode = st.session_state["mode"]

    if st.button("📚 指標說明（隨時複習）", width="stretch", key="open_glossary"):
        _show_glossary_dialog()
    st.divider()

    # 用 session_state 持久化股票代碼，避免 rerun 後丟失
    if "symbol_text" not in st.session_state:
        st.session_state["symbol_text"] = ""
    # 自選清單點選時把 prefill 移入 symbol_text
    if "symbol_prefill" in st.session_state:
        st.session_state["symbol_text"] = st.session_state.pop("symbol_prefill")

    symbol_input = st.text_input(
        "股票代碼 / 名稱",
        key="symbol_text",
        placeholder="輸入代碼或名稱：Tesla / 台積電 / 2330 / VOO",
        help="可輸入代碼（TSLA、2330、0050）或公司名稱（Tesla、台積電）",
    ).strip()

    # ── 智能建議：輸入時自動顯示符合的候選 ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_search(q: str):
        return search_stocks(q, limit=6)

    _is_exact_ticker = (
        symbol_input.isdigit()                       # 純數字（台股）
        or "." in symbol_input                       # 含後綴 (.TW / .HK)
        or (symbol_input.isalpha() and symbol_input.isupper() and 1 <= len(symbol_input) <= 5)  # 全大寫英文代碼
    )

    if symbol_input and len(symbol_input) >= 2:
        with st.spinner("搜尋中...") if not _is_exact_ticker else st.empty():
            _matches = _cached_search(symbol_input)
        # 排除跟當前輸入完全相同的（避免列自己）
        _matches = [m for m in _matches if m["symbol"].upper() != symbol_input.upper()]
        if _matches:
            st.caption("🔍 可能符合（點選即分析）：")
            for _idx, m in enumerate(_matches[:5]):
                _lbl = f"{m['symbol']}  ·  {m['name'][:22]}"
                if m.get("exchange"):
                    _lbl += f"  ({m['exchange']})"
                if st.button(_lbl, key=f"match_{_idx}_{m['symbol']}", width="stretch"):
                    st.session_state["symbol_prefill"] = m["symbol"]
                    st.session_state["auto_analyze"] = True
                    st.rerun()

    st.subheader("資金設定")
    monthly_budget = st.number_input(
        "每月預算（新台幣 NT$）",
        min_value=1000,
        max_value=10_000_000,
        value=10_000,
        step=1000,
        format="%d",
    )

    risk_pref = st.radio(
        "風險偏好",
        ["保守", "中性", "積極"],
        index=1,
        horizontal=True,
    )

    st.subheader("持倉資訊（選填）")
    cost_basis = st.number_input(
        "平均持有成本",
        min_value=0.0,
        value=0.0,
        step=0.01,
        help="輸入 0 表示尚未持有",
    )

    _analyze_clicked = st.button("開始分析", type="primary", width="stretch")
    # 觸發分析後保持「已分析」狀態，rerun 不會丟掉結果
    if _analyze_clicked or st.session_state.get("auto_analyze", False):
        st.session_state["analyzed_symbol"] = symbol_input
        st.session_state["auto_analyze"] = False

    # 只要 analyzed_symbol 還是當前輸入，就持續顯示分析結果
    analyze_btn = bool(
        symbol_input
        and st.session_state.get("analyzed_symbol", "").upper() == symbol_input.upper()
    )
    st.divider()

    # Watchlist
    st.subheader("自選清單")
    st.caption("點代碼可直接分析")
    watchlist = get_watchlist()
    if watchlist:
        for item in watchlist:
            col1, col2 = st.columns([3, 1])
            if col1.button(item["symbol"], key=f"wl_{item['symbol']}", width="stretch"):
                st.session_state["symbol_prefill"] = item["symbol"]
                st.session_state["auto_analyze"] = True
                st.rerun()
            if col2.button("×", key=f"rm_{item['symbol']}"):
                remove_from_watchlist(item["symbol"])
                st.rerun()
    else:
        st.caption("（尚無標的）")

    if symbol_input and st.button("加入自選", width="stretch"):
        add_to_watchlist(symbol_input)
        st.success(f"{symbol_input.upper()} 已加入自選")
        st.rerun()

    st.divider()

    # ntfy.sh push notification settings
    st.subheader("推播通知設定 (ntfy.sh)")
    st.caption("手機下載 ntfy App → 訂閱下方主題 → 即可收到警報")

    _saved_topic = get_topic() or ""
    _topic_input = st.text_input(
        "通知主題 (Topic)",
        value=_saved_topic,
        placeholder="例：my-invest-alerts-9j2k",
        help="自訂一組難猜的字串當主題，任何人知道都能訂閱，請勿用常見字",
    )
    if _topic_input != _saved_topic:
        set_topic(_topic_input)
        st.success("主題已儲存")

    with st.expander("進階：自訂 ntfy 伺服器"):
        _saved_server = get_server()
        _server_input = st.text_input(
            "Server URL",
            value=_saved_server,
            help="預設 https://ntfy.sh，可改成自架伺服器",
        )
        if _server_input != _saved_server:
            set_server(_server_input)
            st.success("Server 已儲存")

    if _topic_input:
        if st.button("發送測試通知", width="stretch"):
            ok, msg = send(
                "ntfy 連線測試成功！",
                _topic_input,
                title="✅ 投資工具測試",
                tags="white_check_mark",
            )
            st.success(msg) if ok else st.error(msg)
    else:
        st.caption("設定主題後可接收補倉/減碼警報")

    st.divider()

    # ── 自動掃描設定（僅本機 Windows 可用） ──────────
    if IS_WINDOWS:
        st.subheader("自動掃描排程")
        st.caption("Windows 工作排程器每日定時掃描自選清單，觸發訊號自動推播")

        _saved_times = get_scan_times()
        _scan_count = st.number_input(
            "每日掃描次數",
            min_value=1,
            max_value=6,
            value=len(_saved_times) if 1 <= len(_saved_times) <= 6 else 3,
            step=1,
        )

        _time_inputs = []
        _defaults = (_saved_times + ["09:00", "13:30", "21:30", "07:00", "12:00", "18:00"])[:_scan_count]
        for i in range(_scan_count):
            try:
                hh, mm = _defaults[i].split(":")
                from datetime import time as _t
                _default_time = _t(int(hh), int(mm))
            except Exception:
                _default_time = None
            t = st.time_input(
                f"第 {i+1} 次掃描時間",
                value=_default_time,
                key=f"scan_time_{i}",
                step=300,
            )
            _time_inputs.append(t.strftime("%H:%M"))

        _dedup = st.slider(
            "同訊號去重時間（小時）",
            min_value=1, max_value=168, value=get_dedup_hours(), step=1,
            help="同一檔股票同一訊號在此時間內只通知一次",
        )

        _sig = get_signal_filter()
        _col_a, _col_b = st.columns(2)
        _sig_add = _col_a.checkbox("補倉訊號", value=_sig["add"])
        _sig_red = _col_b.checkbox("減碼訊號", value=_sig["reduce"])

        if st.button("儲存並安裝排程", type="primary", width="stretch"):
            set_scan_times(_time_inputs)
            set_dedup_hours(_dedup)
            set_signal_filter(_sig_add, _sig_red)
            ok, msg = scheduler.install_tasks(_time_inputs)
            if ok:
                st.success(f"✅ {msg}")
            else:
                st.error(msg)

        _existing = scheduler.list_tasks()
        if _existing:
            with st.expander(f"目前已安裝 {len(_existing)} 個排程"):
                for t in _existing:
                    st.code(t, language=None)
                if st.button("移除全部排程", width="stretch"):
                    ok, msg = scheduler.uninstall_all()
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()

        if st.button("立即掃描一次（測試）", width="stretch"):
            with st.spinner("掃描中..."):
                ok, output = scheduler.run_now()
            if ok:
                st.success("掃描完成，詳見 data/scan.log")
            else:
                st.error("掃描失敗")
            with st.expander("執行輸出"):
                st.code(output or "(無輸出)", language=None)
    else:
        st.caption("（自動掃描排程僅在本機 Windows 版本可用,雲端版本請改用其他排程服務）")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
st.title("長期投資決策工具")

# 全局市場狀態 banner + 大盤走勢圖
_render_market_banner()
_render_market_charts()
st.divider()

# ─────────────────────────────────────────────
# 投資組合總覽模式
# ─────────────────────────────────────────────
if mode == "總覽":
    st.subheader("💼 投資組合總覽")
    st.caption("彙整所有持倉的成本、現值、損益與配置分布（現價即時抓取）")

    _all_holdings = get_holdings()
    if not _all_holdings:
        st.info("尚無持倉，先到「📒 帳務」記錄買進交易後再回來看總覽")
        st.stop()

    _ov_secs = st.selectbox(
        "更新頻率",
        options=[0, 10, 30, 60],
        format_func=lambda x: {0: "暫停", 10: "每 10 秒", 30: "每 30 秒", 60: "每 1 分鐘"}[x],
        index=2,
        key="ov_refresh_secs",
        help="自動重抓現價更新總覽；盤後或夜間建議調至暫停",
    )

    @st.fragment(run_every=f"{_ov_secs}s" if _ov_secs > 0 else None)
    def _render_overview():
        rows = []
        total_cost = total_value = 0.0
        mkt_value = {"台股": 0.0, "美股": 0.0, "其他": 0.0}
        for h in _all_holdings:
            q = _cached_quote(h["symbol"])
            cur_price = q["cur_price"] if q else None
            name = q["name"] if q else h["symbol"]
            cur_value_twd, pnl_twd, pnl_pct = _holding_value_twd(h, cur_price)
            total_cost += h["twd_cost"]
            total_value += cur_value_twd
            mkt = _classify_market(h["symbol"], h.get("currency"))
            mkt_value[mkt] = mkt_value.get(mkt, 0.0) + cur_value_twd
            rows.append({
                "symbol": h["symbol"], "name": name, "market": mkt,
                "shares": h["shares"], "cur_price": cur_price,
                "cost": h["twd_cost"], "value": cur_value_twd,
                "pnl": pnl_twd, "pnl_pct": pnl_pct,
            })

        total_pnl = total_value - total_cost
        total_pct = (total_pnl / total_cost * 100) if total_cost else 0

        # ── 關鍵數字 ──
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("持倉檔數", f"{len(rows)} 檔")
        m2.metric("總成本", f"NT${total_cost:,.0f}")
        m3.metric("估計現值", f"NT${total_value:,.0f}")
        m4.metric("未實現損益", f"NT${total_pnl:+,.0f}", f"{total_pct:+.2f}%")

        st.divider()

        # ── 兩個圓餅：各標的占比 / 市場分布 ──
        _value_rows = [r for r in rows if r["value"] > 0]
        col_a, col_b = st.columns(2)
        with col_a:
            if _value_rows:
                pie1 = go.Figure(go.Pie(
                    labels=[r["symbol"] for r in _value_rows],
                    values=[r["value"] for r in _value_rows],
                    hole=0.45, textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>現值 NT$%{value:,.0f}<br>%{percent}<extra></extra>",
                ))
                pie1.update_layout(
                    title="各標的現值占比", height=340,
                    margin=dict(l=10, r=10, t=50, b=10), showlegend=False,
                    paper_bgcolor="#0e1117", font=dict(color="white"),
                )
                st.plotly_chart(pie1, width="stretch")
            else:
                st.caption("（無可顯示的現值，請確認交易有填台幣金額）")
        with col_b:
            _mkt_items = [(k, v) for k, v in mkt_value.items() if v > 0]
            if _mkt_items:
                pie2 = go.Figure(go.Pie(
                    labels=[k for k, _ in _mkt_items],
                    values=[v for _, v in _mkt_items],
                    hole=0.45, textinfo="label+percent",
                    marker_colors=["#f39c12", "#9b59b6", "#7f8c8d"],
                    hovertemplate="<b>%{label}</b><br>現值 NT$%{value:,.0f}<br>%{percent}<extra></extra>",
                ))
                pie2.update_layout(
                    title="市場分布（台股 / 美股）", height=340,
                    margin=dict(l=10, r=10, t=50, b=10),
                    paper_bgcolor="#0e1117", font=dict(color="white"),
                )
                st.plotly_chart(pie2, width="stretch")

        st.divider()

        # ── 各標的未實現損益長條（台股慣例：紅賺綠賠）──
        _sorted = sorted(rows, key=lambda r: r["pnl"], reverse=True)
        bar = go.Figure(go.Bar(
            x=[r["pnl"] for r in _sorted],
            y=[r["symbol"] for r in _sorted],
            orientation="h",
            marker_color=["#e74c3c" if r["pnl"] > 0 else "#2ecc71" if r["pnl"] < 0 else "#95a5a6"
                          for r in _sorted],
            text=[f"{r['pnl']:+,.0f} ({r['pnl_pct']:+.1f}%)" for r in _sorted],
            textposition="auto",
            hovertemplate="<b>%{y}</b><br>未實現 NT$%{x:,.0f}<extra></extra>",
        ))
        bar.update_layout(
            title="各標的未實現損益（NT$）",
            height=max(220, 38 * len(_sorted) + 90),
            margin=dict(l=10, r=10, t=50, b=30),
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="white"),
            xaxis=dict(zeroline=True, zerolinecolor="rgba(255,255,255,0.3)",
                       gridcolor="rgba(255,255,255,0.05)"),
        )
        st.plotly_chart(bar, width="stretch")
        st.caption("🔴 紅 = 帳面獲利　🟢 綠 = 帳面虧損（台股紅漲綠跌慣例）")

        # ── 明細表 ──
        df = pd.DataFrame([{
            "代碼": r["symbol"],
            "名稱": r["name"][:18],
            "市場": r["market"],
            "股數": round(r["shares"], 4),
            "現價": round(r["cur_price"], 4) if r["cur_price"] else None,
            "成本(NT$)": round(r["cost"]),
            "現值(NT$)": round(r["value"]),
            "損益(NT$)": round(r["pnl"]),
            "報酬率": f"{r['pnl_pct']:+.2f}%",
        } for r in _sorted])
        st.dataframe(df, width="stretch", hide_index=True)

    _render_overview()
    st.caption("💡 現值/損益的匯率以建倉成本內含值近似（未反映即時匯率變動）；"
               "已實現損益與已出清標的未納入，僅供參考。")
    st.stop()


# ─────────────────────────────────────────────
# 多標配置模式
# ─────────────────────────────────────────────
if mode == "多標配置":
    st.subheader("🎯 多標的資產配置")
    st.caption("從已分析過的股票中挑選，依基本面 × 風險 × 估值自動計算建議權重")

    hist = get_history(limit=50, unique_symbols=True)
    if not hist:
        st.info("尚無分析紀錄，請先到「單檔分析」分析幾檔股票後再回來配置")
        st.stop()

    hist_map = {h["symbol"]: h for h in hist}
    all_syms = list(hist_map.keys())
    wl_syms = {w["symbol"] for w in get_watchlist()}
    default_syms = [s for s in all_syms if s in wl_syms] or all_syms[: min(5, len(all_syms))]

    picked = st.multiselect(
        "挑選標的（預設自選清單中的標的）",
        all_syms,
        default=default_syms,
        help="先在「單檔分析」分析過的股票才會出現在此",
    )

    col_budget, col_cap, col_min, col_mkt = st.columns(4)
    with col_budget:
        port_budget = st.number_input(
            "總投入資金（NT$）",
            min_value=10_000,
            max_value=100_000_000,
            value=300_000,
            step=10_000,
            format="%d",
        )
    with col_cap:
        max_single = st.slider("單檔上限 (%)", 10, 100, 30, 5) / 100
    with col_min:
        min_score = st.slider("最低基本面分數", 0, 100, 50, 5)
    with col_mkt:
        _reg = _cached_market_regime()
        _default_apply = _reg.get("available", False)
        apply_market = st.checkbox(
            "套用市場乘數",
            value=_default_apply,
            help=f"目前 {_reg.get('regime','N/A')} ×{_reg.get('budget_multiplier',1):.2f}" if _default_apply else "無法取得大盤資料",
        )

    if apply_market and _reg.get("available"):
        port_budget_eff = port_budget * _reg["budget_multiplier"]
        st.caption(f"💡 大盤「{_reg['regime']}」乘數 ×{_reg['budget_multiplier']:.2f}：實際配置資金 NT${port_budget_eff:,.0f}")
    else:
        port_budget_eff = port_budget

    if not picked:
        st.warning("請至少選一檔標的")
        st.stop()

    stocks = []
    for sym in picked:
        h = hist_map[sym]
        stocks.append({
            "symbol": sym,
            "fundamental_score": h.get("fundamental_score") or 0,
            "risk_level": h.get("risk_level"),
            "valuation_status": h.get("valuation_status"),
            "recommendation": h.get("recommendation"),
            "analyzed_at": h.get("analyzed_at", "")[:16],
        })

    result = portfolio.allocate(
        stocks,
        total_budget=port_budget_eff,
        max_single=max_single,
        min_score=float(min_score),
    )

    allocs = result["allocations"]
    excluded = result["excluded"]

    if not allocs:
        st.error("所選標的全部不符合配置條件（見下方排除清單）")
    else:
        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("納入標的", f"{len(allocs)} 檔")
        m2.metric("排除標的", f"{len(excluded)} 檔")
        avg_score = sum(a["fundamental_score"] for a in allocs) / len(allocs)
        m3.metric("組合平均基本面", f"{avg_score:.0f} / 100")
        m4.metric("總投入", f"NT${port_budget_eff:,.0f}")

        st.divider()

        # Pie chart + table side by side
        col_pie, col_tbl = st.columns([1, 1.3])
        with col_pie:
            pie = go.Figure(go.Pie(
                labels=[a["symbol"] for a in allocs],
                values=[a["weight"] for a in allocs],
                hole=0.45,
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>權重 %{percent}<br>金額 NT$%{customdata:,.0f}<extra></extra>",
                customdata=[a["amount"] for a in allocs],
            ))
            pie.update_layout(
                title="資金配置比例",
                height=380,
                margin=dict(l=10, r=10, t=50, b=10),
                showlegend=False,
            )
            st.plotly_chart(pie, width="stretch")

        with col_tbl:
            # 從帳務拉持倉，比對每個配置標的
            _holdings_map = {h["symbol"]: h for h in get_holdings()}
            rows = []
            for a in allocs:
                _h = _holdings_map.get(a["symbol"])
                _hold_cost_twd = _h["twd_cost"] if _h else 0
                _to_invest = max(0, a["amount"] - _hold_cost_twd)
                rows.append({
                    "代碼": a["symbol"],
                    "目標權重": f"{a['weight']*100:.1f}%",
                    "目標金額": f"NT${a['amount']:,.0f}",
                    "目前持倉": f"NT${_hold_cost_twd:,.0f}" if _h else "—",
                    "需追加": f"NT${_to_invest:,.0f}" if _h else f"NT${a['amount']:,.0f}",
                    "基本面": f"{a['fundamental_score']:.0f}",
                    "風險": a.get("risk_level") or "-",
                    "估值": a.get("valuation_status") or "-",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("💡「需追加」= 目標金額 − 目前持倉，告訴你還要買多少才達到配置比例")

        st.divider()
        st.subheader("配置理由")
        for a in allocs:
            st.markdown(f"**{a['symbol']}** — {a['weight']*100:.1f}%  ·  NT${a['amount']:,.0f}")
            st.caption(a["rationale"])

    if excluded:
        with st.expander(f"排除清單（{len(excluded)} 檔）"):
            ex_rows = [{
                "代碼": e["symbol"],
                "基本面": f"{(e.get('fundamental_score') or 0):.0f}",
                "建議": e.get("recommendation") or "-",
                "排除原因": e.get("exclude_reason", ""),
            } for e in excluded]
            st.dataframe(pd.DataFrame(ex_rows), width="stretch", hide_index=True)

    st.stop()


# ─────────────────────────────────────────────
# 帳務模式
# ─────────────────────────────────────────────
if mode == "帳務":
    from datetime import date as _date, timedelta as _td
    st.subheader("📒 帳務")
    st.caption("記錄每筆買賣，自動計算加權平均成本，給自動掃描判斷補倉訊號")

    _market_filter = st.radio(
        "市場",
        ["🌐 全部", "🇹🇼 台股", "🇺🇸 美股"],
        horizontal=True,
        label_visibility="collapsed",
    )
    _market_key = {"🌐 全部": None, "🇹🇼 台股": "台股", "🇺🇸 美股": "美股"}[_market_filter]

    # ── 新增交易 form ─────────────────────────
    with st.expander("➕ 新增交易", expanded=False):
        # 股票代碼 + 智能搜尋（必須放在 form 外，搜尋結果按鈕才能 click 寫入 state）
        # 用 prefill 中間鍵避免「widget 渲染後改 session_state」的錯
        if "tx_symbol_pick" not in st.session_state:
            st.session_state["tx_symbol_pick"] = ""
        if "tx_symbol_prefill" in st.session_state:
            st.session_state["tx_symbol_pick"] = st.session_state.pop("tx_symbol_prefill")

        _sym_typed = st.text_input(
            "股票代碼 / 名稱",
            key="tx_symbol_pick",
            placeholder="例：TSLA / 2330 / Tesla / 台積電",
            help="可輸入代碼或公司名，下方會出現候選清單",
        ).strip()

        if _sym_typed and len(_sym_typed) >= 2:
            _tx_matches = _cached_search(_sym_typed)
            _tx_matches = [m for m in _tx_matches if m["symbol"].upper() != _sym_typed.upper()]
            if _tx_matches:
                st.caption("🔍 可能符合（點選帶入）：")
                for _idx, m in enumerate(_tx_matches[:5]):
                    _lbl = f"{m['symbol']}  ·  {m['name'][:22]}"
                    if m.get("exchange"):
                        _lbl += f"  ({m['exchange']})"
                    if st.button(_lbl, key=f"tx_match_{_idx}_{m['symbol']}", width="stretch"):
                        st.session_state["tx_symbol_prefill"] = m["symbol"]
                        st.rerun()

        tx_symbol = _sym_typed.upper()

        # ── 表單其餘欄位（不用 st.form，讓幣別切換可即時改 label）──
        c2, c3 = st.columns([1, 1])
        tx_action = c2.selectbox("買賣", ["買進", "賣出"], key="tx_action")
        tx_date = c3.date_input("交易日期", value=_date.today(), key="tx_date")

        c4, c5, c6 = st.columns([1, 1, 1])
        tx_price = c4.number_input(
            "成交單價（原幣）", min_value=0.0, value=0.0, step=0.01, format="%.4f",
            key="tx_price",
        )
        tx_shares = c5.number_input(
            "股數", min_value=0.0, value=0.0, step=1.0, format="%.4f",
            key="tx_shares",
        )
        tx_currency = c6.selectbox(
            "計價幣別", ["TWD", "USD", "HKD", "JPY", "EUR"], index=0,
            key="tx_currency",
        )

        c7, c8 = st.columns([1, 1])
        with c7:
            # 外幣股票：可選 NT$ 或原幣輸入金額；台股：固定 NT$
            if tx_currency != "TWD":
                _amt_ccy = st.radio(
                    "金額幣別",
                    ["NT$", tx_currency],
                    horizontal=True,
                    key="tx_amt_ccy",
                    label_visibility="collapsed",
                )
            else:
                _amt_ccy = "NT$"

            if _amt_ccy == "NT$":
                _auto = tx_price * tx_shares if tx_currency == "TWD" else 0.0
                _amt_input = st.number_input(
                    "台幣總額（手續費含）", min_value=0.0,
                    value=_auto, step=100.0, format="%.0f",
                    key="tx_amt_twd",
                    help="實際扣款台幣金額；台股可留空自動 = 單價 × 股數",
                )
                tx_twd = _amt_input
            else:
                _auto_native = tx_price * tx_shares
                _amt_input = st.number_input(
                    f"{tx_currency} 總額（手續費含）", min_value=0.0,
                    value=_auto_native, step=1.0, format="%.4f",
                    key="tx_amt_native",
                    help=f"實際扣款 {tx_currency} 金額（含手續費）",
                )
                # 換算成 TWD 存進 DB
                _fx_native_to_twd = _cached_fx(tx_currency, "TWD")
                tx_twd = _amt_input * _fx_native_to_twd if _fx_native_to_twd else 0
                if _fx_native_to_twd and _amt_input > 0:
                    st.caption(f"≈ NT${tx_twd:,.0f}（匯率 {_fx_native_to_twd:.4f}）")

        tx_note = c8.text_input(
            "備註（選填）", placeholder="如：定期定額 / 第X次補倉",
            key="tx_note",
        )

        submitted = st.button(
            "儲存交易", type="primary", width="stretch",
            key="tx_submit",
        )
        if submitted:
            if not tx_symbol or tx_price <= 0 or tx_shares <= 0:
                st.error("請填寫代碼、單價、股數")
            else:
                final_twd = tx_twd
                if tx_currency != "TWD" and final_twd <= 0:
                    fx = _cached_fx(tx_currency, "TWD")
                    if fx:
                        final_twd = tx_price * tx_shares * fx
                add_transaction(
                    symbol=tx_symbol,
                    action="buy" if tx_action == "買進" else "sell",
                    trade_date=tx_date.isoformat(),
                    price=tx_price,
                    shares=tx_shares,
                    twd_amount=final_twd if final_twd > 0 else None,
                    currency=tx_currency,
                    note=tx_note,
                )
                st.success(f"已記錄：{tx_action} {tx_symbol} × {tx_shares}")
                # 清空輸入
                for _k in ("tx_price", "tx_shares", "tx_amt_twd",
                           "tx_amt_native", "tx_note"):
                    if _k in st.session_state:
                        del st.session_state[_k]
                st.session_state["tx_symbol_prefill"] = ""
                st.rerun()

    # ── 持倉總覽 ──────────────────────────────
    holdings = get_holdings()
    # 篩選
    holdings_filtered = [
        h for h in holdings
        if _market_key is None or _classify_market(h["symbol"], h.get("currency")) == _market_key
    ]
    st.subheader(f"目前持倉{(' — ' + _market_key) if _market_key else ''}")
    if not holdings_filtered:
        if holdings:
            st.caption(f"（{_market_key} 無持倉）")
        else:
            st.caption("（尚無持倉，先新增買進交易）")
    else:
        # ── 自動更新設定 ──
        _refresh_col1, _refresh_col2 = st.columns([1, 3])
        _refresh_secs = _refresh_col1.selectbox(
            "更新頻率",
            options=[5, 10, 30, 60, 0],
            format_func=lambda x: {0: "暫停", 5: "每 5 秒", 10: "每 10 秒",
                                    30: "每 30 秒", 60: "每 1 分鐘"}[x],
            index=1,
            key="hold_refresh_secs",
            help="自動重抓現價更新損益。台股盤後或夜間建議調至暫停",
        )

        # 用 fragment 包卡片區段，做局部自動更新（_cached_quote 已在模組層共用）
        @st.fragment(run_every=f"{_refresh_secs}s" if _refresh_secs > 0 else None)
        def _render_holdings_cards():
            total_cost = 0.0
            total_value = 0.0

            for h in holdings_filtered:
                total_cost += h["twd_cost"]
                q = _cached_quote(h["symbol"])
                cur_price = q["cur_price"] if q else None
                name = q["name"] if q else h["symbol"]

                cur_value_twd, pnl_twd, pnl_pct = _holding_value_twd(h, cur_price)
                total_value += cur_value_twd

                # 台股色：紅漲綠跌
                _pnl_color = "#e74c3c" if pnl_pct > 0 else ("#2ecc71" if pnl_pct < 0 else "#95a5a6")

                # 標籤
                _mkt = _classify_market(h["symbol"], h.get("currency"))
                if h["shares"] < 1:
                    _badge_text, _badge_color = "碎股", "#3498db"
                elif _mkt == "美股":
                    _badge_text, _badge_color = "美股", "#9b59b6"
                elif _mkt == "台股":
                    _badge_text, _badge_color = "台股", "#f39c12"
                else:
                    _badge_text, _badge_color = _mkt, "#7f8c8d"

                with st.container(border=True):
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:4px'>"
                        f"<span style='background:{_badge_color};color:white;padding:3px 14px;"
                        f"border-radius:14px;font-size:0.85rem;font-weight:600'>{_badge_text}</span>"
                        f"<span style='font-weight:700;font-size:1.1rem'>{h['symbol']}</span>"
                        f"</div>"
                        f"<div style='font-size:1.3rem;font-weight:600;margin-bottom:12px'>{name}</div>",
                        unsafe_allow_html=True,
                    )

                    r1c1, r1c2 = st.columns([1, 1])
                    r1c1.markdown("<div style='color:#95a5a6'>總股數</div>", unsafe_allow_html=True)
                    r1c2.markdown(
                        f"<div style='text-align:right;font-size:1.2rem;font-weight:500'>{h['shares']:.4f}</div>",
                        unsafe_allow_html=True)
                    r2c1, r2c2 = st.columns([1, 1])
                    r2c1.markdown("<div style='color:#95a5a6'>成交均價</div>", unsafe_allow_html=True)
                    r2c2.markdown(
                        f"<div style='text-align:right;font-size:1.2rem;font-weight:500'>{h['avg_cost']:.4f}</div>",
                        unsafe_allow_html=True)
                    r3c1, r3c2 = st.columns([1, 1])
                    r3c1.markdown("<div style='color:#95a5a6'>總預估損益</div>", unsafe_allow_html=True)
                    r3c2.markdown(
                        f"<div style='text-align:right;font-size:1.2rem;font-weight:700;color:{_pnl_color}'>"
                        f"{pnl_twd:+,.2f} ({pnl_pct:+.2f}%)</div>",
                        unsafe_allow_html=True)

                    st.divider()

                    r4c1, r4c2 = st.columns([1, 1])
                    r4c1.markdown("<div style='color:#95a5a6'>總預估現值</div>", unsafe_allow_html=True)
                    r4c2.markdown(
                        f"<div style='text-align:right;font-size:1.05rem'>NT${cur_value_twd:,.0f}</div>",
                        unsafe_allow_html=True)
                    r5c1, r5c2 = st.columns([1, 1])
                    r5c1.markdown("<div style='color:#95a5a6'>總成本</div>", unsafe_allow_html=True)
                    r5c2.markdown(
                        f"<div style='text-align:right;font-size:1.05rem'>NT${h['twd_cost']:,.0f}</div>",
                        unsafe_allow_html=True)
                    r6c1, r6c2 = st.columns([1, 1])
                    r6c1.markdown("<div style='color:#95a5a6'>最新價</div>", unsafe_allow_html=True)
                    r6c2.markdown(
                        f"<div style='text-align:right;font-size:1.05rem'>"
                        f"{(f'{cur_price:.4f}') if cur_price else '—'}</div>",
                        unsafe_allow_html=True)

                    if h.get("twd_realized"):
                        r7c1, r7c2 = st.columns([1, 1])
                        r7c1.markdown("<div style='color:#95a5a6'>已實現</div>", unsafe_allow_html=True)
                        r7c2.markdown(
                            f"<div style='text-align:right;font-size:1.05rem'>NT${h['twd_realized']:,.0f}</div>",
                            unsafe_allow_html=True)

            # 底部總計（也在 fragment 內，會跟著刷新）
            st.divider()
            m1, m2, m3 = st.columns(3)
            m1.metric("總成本", f"NT${total_cost:,.0f}")
            m2.metric("估計現值", f"NT${total_value:,.0f}")
            _total_pnl = total_value - total_cost
            _total_pct = (_total_pnl / total_cost * 100) if total_cost else 0
            m3.metric("未實現損益", f"NT${_total_pnl:+,.0f}", f"{_total_pct:+.2f}%")

        _render_holdings_cards()

    st.divider()

    # ── 交易日曆 ──────────────────────────────
    st.subheader(f"交易日曆{(' — ' + _market_key) if _market_key else ''}")
    all_tx_raw = get_transactions()
    all_tx = [
        t for t in all_tx_raw
        if _market_key is None or _classify_market(t["symbol"], t.get("currency")) == _market_key
    ]
    if not all_tx:
        st.caption("（無交易紀錄）" if all_tx_raw else "（尚無交易紀錄）")
    else:
        # 聚合每日台幣金額（買 +，賣 -）
        from collections import defaultdict
        daily = defaultdict(float)
        daily_count = defaultdict(int)
        daily_detail = defaultdict(list)
        for t in all_tx:
            d = t["trade_date"]
            amt = (t.get("twd_amount") or 0) * (1 if t["action"] == "buy" else -1)
            daily[d] += amt
            daily_count[d] += 1
            sign = "🟢" if t["action"] == "buy" else "🔴"
            daily_detail[d].append(f"{sign}{t['symbol']} {t['shares']:.2f}股 單價{t['price']:.4f}")

        # 取最近 1 年
        today = _date.today()
        start = today - _td(days=365)
        # 排列成 week x weekday 熱圖（y = 星期幾 0=週一 … 6=週日）
        # 7 列 (週一-週日) × N 欄
        rows_z = {i: [] for i in range(7)}
        rows_text = {i: [] for i in range(7)}
        col_dates = []

        cur = start - _td(days=start.weekday())  # 對齊到週一
        while cur <= today:
            col_dates.append(cur)
            for dow in range(7):
                d = cur + _td(days=dow)
                key = d.isoformat()
                val = daily.get(key, 0)
                rows_z[dow].append(val if (start <= d <= today) else None)
                detail = "<br>".join(daily_detail.get(key, []))
                if detail:
                    rows_text[dow].append(f"<b>{key}</b><br>淨額 NT${val:+,.0f}<br>{detail}")
                else:
                    rows_text[dow].append(f"{key}")
            cur += _td(days=7)

        z_matrix = [rows_z[i] for i in range(7)]
        text_matrix = [rows_text[i] for i in range(7)]

        # 月份標籤
        x_tickvals = []
        x_ticktext = []
        last_month = None
        for i, d in enumerate(col_dates):
            if d.month != last_month:
                x_tickvals.append(i)
                x_ticktext.append(f"{d.month}月")
                last_month = d.month

        heat = go.Figure(go.Heatmap(
            z=z_matrix,
            text=text_matrix,
            hovertemplate="%{text}<extra></extra>",
            colorscale=[
                [0.0, "#e74c3c"],   # 大額賣出
                [0.5, "#1e1e2e"],   # 無交易
                [1.0, "#2ecc71"],   # 大額買進
            ],
            zmid=0,
            showscale=True,
            colorbar=dict(title="淨額 NT$", thickness=10),
            xgap=2, ygap=2,
        ))
        heat.update_layout(
            height=240,
            margin=dict(l=40, r=20, t=20, b=30),
            xaxis=dict(
                tickmode="array",
                tickvals=x_tickvals,
                ticktext=x_ticktext,
                showgrid=False,
            ),
            yaxis=dict(
                tickmode="array",
                tickvals=list(range(7)),
                ticktext=["一", "二", "三", "四", "五", "六", "日"],
                autorange="reversed",
                showgrid=False,
            ),
        )
        st.plotly_chart(heat, width="stretch")
        st.caption("綠 = 買進日 / 紅 = 賣出日 / 滑鼠移上去可看當日明細")

    st.divider()

    # ── 交易明細（可編輯）──────────────────────────────
    st.subheader(f"交易明細{(' — ' + _market_key) if _market_key else ''}")
    st.caption("✏️ 直接在表格內修改任何欄位、按 Enter 後上方持倉會自動重算；要刪除請勾選最左欄的 ✕ 後按下方按鈕")

    if not all_tx:
        st.caption("（無紀錄）")
    else:
        # 篩選
        f1, _ = st.columns([1, 3])
        all_syms = sorted(set(t["symbol"] for t in all_tx))
        filter_sym = f1.selectbox("篩選代碼", ["全部"] + all_syms, key="tx_filter_sym")
        shown = [t for t in all_tx if filter_sym == "全部" or t["symbol"] == filter_sym]

        if not shown:
            st.caption("（沒有符合的紀錄）")
        else:
            # 準備 dataframe 給 data_editor
            # 非 TWD 的列：把 twd_amount 反換算回原幣金額方便編輯
            df_rows = []
            for t in shown:
                ccy = t.get("currency") or "TWD"
                twd_amt = float(t.get("twd_amount") or 0)
                if ccy != "TWD" and twd_amt > 0:
                    fx_twd_to_native = _cached_fx("TWD", ccy)
                    native_amt = twd_amt * fx_twd_to_native if fx_twd_to_native else twd_amt
                else:
                    native_amt = twd_amt
                df_rows.append({
                    "id": t["id"],
                    "刪除": False,
                    "日期": t["trade_date"],
                    "動作": "買進" if t["action"] == "buy" else "賣出",
                    "代碼": t["symbol"],
                    "股數": float(t["shares"]),
                    "單價(原幣)": float(t["price"]),
                    "幣別": ccy,
                    "金額(原幣)": float(native_amt),
                    "備註": t.get("note") or "",
                })
            edit_df = pd.DataFrame(df_rows)

            edited = st.data_editor(
                edit_df,
                key="tx_editor",
                hide_index=True,
                width="stretch",
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                    "刪除": st.column_config.CheckboxColumn(
                        "✕", help="勾起來後按下方「刪除勾選」", width="small",
                    ),
                    "日期": st.column_config.TextColumn("日期", help="YYYY-MM-DD"),
                    "動作": st.column_config.SelectboxColumn(
                        "動作", options=["買進", "賣出"], required=True,
                    ),
                    "代碼": st.column_config.TextColumn("代碼", required=True),
                    "股數": st.column_config.NumberColumn("股數", format="%.4f", step=0.0001),
                    "單價(原幣)": st.column_config.NumberColumn("單價(原幣)", format="%.4f", step=0.0001),
                    "幣別": st.column_config.SelectboxColumn(
                        "幣別", options=["TWD", "USD", "HKD", "JPY", "EUR"],
                    ),
                    "金額(原幣)": st.column_config.NumberColumn(
                        "金額(原幣)", format="%.2f", step=0.01,
                        help="輸入該幣別的實際金額（含手續費）。儲存時自動換算成台幣存進帳本",
                    ),
                    "備註": st.column_config.TextColumn("備註"),
                },
                column_order=["刪除", "日期", "動作", "代碼", "股數",
                              "幣別", "金額(原幣)", "備註"],
            )

            # 比對差異並儲存
            col_save, col_del = st.columns([1, 1])
            if col_save.button("💾 儲存修改", type="primary", width="stretch"):
                changes = 0
                edit_lookup = {int(r["id"]): r for _, r in edited.iterrows()}
                for orig in shown:
                    new_row = edit_lookup.get(int(orig["id"]))
                    if new_row is None:
                        continue
                    # 金額換算：非 TWD → 用即時匯率算成台幣存
                    new_ccy = str(new_row["幣別"])
                    new_native = float(new_row["金額(原幣)"])
                    if new_ccy != "TWD" and new_native > 0:
                        _fx = _cached_fx(new_ccy, "TWD")
                        new_twd = new_native * _fx if _fx else new_native
                    else:
                        new_twd = new_native

                    diff = {}
                    field_map = {
                        "trade_date": str(new_row["日期"]),
                        "action": "buy" if new_row["動作"] == "買進" else "sell",
                        "symbol": str(new_row["代碼"]).upper(),
                        "shares": float(new_row["股數"]),
                        "price": float(new_row["單價(原幣)"]),
                        "currency": new_ccy,
                        "twd_amount": new_twd,
                        "note": str(new_row["備註"]),
                    }
                    orig_map = {
                        "trade_date": orig["trade_date"],
                        "action": orig["action"],
                        "symbol": orig["symbol"],
                        "shares": float(orig["shares"]),
                        "price": float(orig["price"]),
                        "currency": orig.get("currency") or "TWD",
                        "twd_amount": float(orig.get("twd_amount") or 0),
                        "note": orig.get("note") or "",
                    }
                    for k, v in field_map.items():
                        if v != orig_map.get(k):
                            diff[k] = v
                    if diff:
                        update_transaction(int(orig["id"]), **diff)
                        changes += 1
                if changes:
                    st.success(f"已更新 {changes} 筆交易，持倉重新計算中...")
                    st.rerun()
                else:
                    st.info("沒有偵測到變更")

            if col_del.button("🗑️ 刪除勾選", width="stretch"):
                to_delete = [int(r["id"]) for _, r in edited.iterrows() if r.get("刪除")]
                if not to_delete:
                    st.info("沒有勾選任何項目")
                else:
                    for tx_id in to_delete:
                        delete_transaction(tx_id)
                    st.success(f"已刪除 {len(to_delete)} 筆交易")
                    st.rerun()

    st.stop()


if not analyze_btn:
    st.info("在左側輸入股票代碼後，點擊「開始分析」")

    # Show recent history — one row per symbol (latest only)
    hist = get_history(limit=20, unique_symbols=True)
    if hist:
        st.subheader("近期分析紀錄")
        rows = []
        for h in hist:
            rows.append({
                "代碼": h["symbol"],
                "最後分析": h["analyzed_at"][:16],
                "基本面": h["fundamental_score"],
                "風險": h["risk_level"],
                "估值": h["valuation_status"],
                "建議": h["recommendation"],
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.stop()


if not symbol_input:
    st.warning("請輸入股票代碼")
    st.stop()


# ── Fetch data（快取 10 分鐘；同一檔的 rerun 直接命中，不再每次重抓）────
with st.spinner(f"正在抓取 {symbol_input.upper()} 資料..."):
    used_sym, data = _cached_fetch(symbol_input)

if data is None:
    st.error(f"找不到 {symbol_input}，請確認代碼正確（台灣股票使用數字代碼，如 0050、2330）")
    st.stop()

with st.spinner("分析中..."):
    info = data["info"]

    fund_result = fundamental.calculate(data)
    risk_result = risk.calculate(data)
    val_result = valuation.calculate(data)

    ma200_bias = val_result.get("ma200_bias")

    # FX conversion: budget is always TWD; convert to stock's native currency
    stock_currency = info.get("currency", "TWD")
    twd_budget = float(monthly_budget)
    fx_rate = None      # 1 TWD = ? stock_currency
    budget_in_stock_ccy = twd_budget
    if stock_currency not in ("TWD", ""):
        fx_rate = _cached_fx("TWD", stock_currency)
        if fx_rate:
            budget_in_stock_ccy = twd_budget * fx_rate

    _regime = _cached_market_regime()
    _mkt_mult = _regime.get("budget_multiplier", 1.0) if _regime.get("available") else 1.0
    _mkt_label = _regime.get("regime") if _regime.get("available") else None

    # 持倉佔月預算的倍數（用台幣比較）— 給 allocation 判斷部位是否過大
    _existing_months = None
    _hold_for_alloc = next((h for h in get_holdings() if h["symbol"] == used_sym), None)
    if _hold_for_alloc and twd_budget > 0:
        _existing_months = float(_hold_for_alloc["twd_cost"]) / float(twd_budget)

    alloc_result = allocation.calculate(
        monthly_budget=budget_in_stock_ccy,
        valuation_status=val_result["status"],
        ma200_bias=ma200_bias,
        risk_level=risk_result["level"],
        fundamental_score=fund_result["total_score"],
        market_mult=_mkt_mult,
        market_regime=_mkt_label,
        existing_position_months=_existing_months,
    )
    # Attach FX info for display
    alloc_result["twd_budget"] = twd_budget
    alloc_result["stock_currency"] = stock_currency
    alloc_result["fx_rate"] = fx_rate
    alloc_result["twd_invest"] = twd_budget * alloc_result["invest_ratio"]
    alloc_result["twd_reserve"] = twd_budget * alloc_result["cash_ratio"]

    current_price = (
        safe_float(info.get("currentPrice"))
        or safe_float(info.get("regularMarketPrice"))
        or safe_float(info.get("previousClose"))
    )

    # 自動從帳務帶入持倉資料（如果有的話）
    _auto_hold = next((h for h in get_holdings() if h["symbol"] == used_sym), None)
    if cost_basis > 0:
        # 使用者手動輸入優先
        _effective_cost = float(cost_basis)
        _cost_source = "手動輸入"
    elif _auto_hold:
        _effective_cost = float(_auto_hold["avg_cost"])
        _cost_source = "帳務"
    else:
        _effective_cost = None
        _cost_source = None

    pos_result = position.calculate(
        fundamental_score=fund_result["total_score"],
        risk_level=risk_result["level"],
        valuation_status=val_result["status"],
        ma200_bias=ma200_bias,
        cost_basis=_effective_cost,
        current_price=current_price,
    )

    # Save to DB
    ccy_sym = "NT$" if info.get("currency") == "TWD" else ("$" if info.get("currency") == "USD" else (info.get("currency", "") + " "))
    price_str_notify = f"{ccy_sym}{current_price:,.2f}" if current_price else "N/A"
    full_result = {
        "fundamental": fund_result,
        "risk": risk_result,
        "valuation": val_result,
        "allocation": alloc_result,
        "position": pos_result,
        "current_price_str": price_str_notify,
    }
    # 每檔每天只寫一筆 analysis_history，避免 rerun（記錄交易、改設定…）灌爆紀錄
    _save_key = f"{used_sym}|{datetime.now():%Y-%m-%d}"
    if st.session_state.get("_last_analysis_saved") != _save_key:
        save_analysis(used_sym, full_result)
        st.session_state["_last_analysis_saved"] = _save_key

    # 將完整結果存到 session，給「手動發送通知」按鈕使用
    st.session_state["_last_full_result"] = full_result
    st.session_state["_last_symbol"] = used_sym


# ── Stock header ───────────────────────────────
name = info.get("longName") or info.get("shortName") or used_sym
currency = info.get("currency", "")
exchange = info.get("exchange", "")

st.subheader(f"{name}  ({used_sym})")
col_p1, col_p2, col_p3, col_p4 = st.columns(4)
with col_p1:
    st.metric("目前股價", price_str_notify)
with col_p2:
    st.metric("交易所", exchange or "N/A")
with col_p3:
    mc = safe_float(info.get("marketCap"))
    mc_str = f"{mc/1e9:.1f}B" if mc and mc >= 1e9 else f"{mc/1e6:.0f}M" if mc else "N/A"
    st.metric("市值", mc_str)
with col_p4:
    sector = info.get("sector") or info.get("category") or ("ETF" if data["is_etf"] else "N/A")
    st.metric("產業/類型", sector)

# ── 帳務持倉自動帶入提示 ─────────────────────────
if _auto_hold and cost_basis <= 0:
    _pnl_pct_hint = ((current_price - _auto_hold["avg_cost"]) / _auto_hold["avg_cost"] * 100) if current_price and _auto_hold["avg_cost"] else 0
    _pnl_color_hint = "🟢" if _pnl_pct_hint < 0 else "🔴" if _pnl_pct_hint > 0 else "⚪"
    st.info(
        f"📒 **已從帳務帶入持倉**：{_auto_hold['shares']:.4f} 股 · "
        f"成交均價 {_auto_hold['avg_cost']:.4f} {_auto_hold.get('currency', '')} · "
        f"{_pnl_color_hint} 損益 {_pnl_pct_hint:+.2f}%  ｜  "
        f"建倉策略已套用此成本判斷補倉/減碼訊號"
    )
elif cost_basis > 0:
    st.info(f"📌 使用手動輸入成本 {cost_basis:.4f} 進行分析（如要用帳務持倉，請把側邊「平均持有成本」清成 0）")

st.divider()


# ── 快速下單 / 帳務記錄 ─────────────────────────
_cur_price_val = current_price or 0.0
_cur_ccy = currency or "TWD"
_existing_hold = next((h for h in get_holdings() if h["symbol"] == used_sym), None)

with st.container(border=True):
    st.markdown(f"### 📝 快速記錄  ·  {used_sym}")
    # 目前持倉用小字 caption 顯示（避免跟成交單價混淆）
    if _existing_hold:
        _avg = _existing_hold["avg_cost"]
        _pnl = (_cur_price_val - _avg) / _avg * 100 if _avg else 0
        _pnl_color = "#e74c3c" if _pnl > 0 else ("#2ecc71" if _pnl < 0 else "#95a5a6")
        st.markdown(
            f"<div style='color:#95a5a6;font-size:0.85rem;margin-top:-8px;margin-bottom:8px'>"
            f"目前持倉 <b>{_existing_hold['shares']:.4f}</b> 股 · "
            f"平均成本 <b>{_avg:,.4f}</b> · "
            f"<span style='color:{_pnl_color}'>{_pnl:+.2f}%</span>"
            f"  <span style='opacity:0.7'>（僅供參考，本筆下單會用下方成交單價）</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("（尚無持倉）")

    _input_mode = st.radio(
        "輸入方式",
        ["依股數", "依台幣金額（支援碎股）"],
        horizontal=True,
        key=f"q_mode_{used_sym}",
        label_visibility="collapsed",
    )

    # 顯示上一筆成功訊息（在 rerun 後仍可看到）
    _last_ok_key = f"_last_tx_msg_{used_sym}"
    if st.session_state.get(_last_ok_key):
        st.success(st.session_state.pop(_last_ok_key))

    # 不使用 st.form，改用普通 widget — 每個 input 變動會自動寫入 session_state，
    # 按下按鈕時 rerun 從 session_state 讀最新值，最可靠
    f1, f2, f3 = st.columns([1, 1, 1.2])
    # 單價鎖定 = 當前市價，不允許手改（避免拍腦袋輸錯）。需改用歷史價請到「📒 帳務」
    with f1:
        st.markdown(
            f"<div style='color:#95a5a6;font-size:0.85rem'>本筆成交單價 ({_cur_ccy})</div>"
            f"<div style='font-size:1.6rem;font-weight:700;color:#3498db'>"
            f"🔒 {_cur_price_val:,.4f}</div>",
            unsafe_allow_html=True,
        )
    q_price = float(_cur_price_val)

    _fx_to_twd = None
    if _cur_ccy != "TWD":
        _fx_to_twd = _cached_fx(_cur_ccy, "TWD")

    # 是否為外幣股票（決定要不要顯示幣別切換）
    _is_foreign = (_cur_ccy != "TWD") and _fx_to_twd

    if _input_mode == "依股數":
        q_shares = f2.number_input(
            "股數", min_value=0.0, value=0.0, step=1.0, format="%.4f",
            key=f"q_sh_{used_sym}",
            help="台股 1 張 = 1000 股；零股可填小數",
        )
        with f3:
            if _is_foreign:
                _amt_ccy = st.radio(
                    "金額幣別",
                    ["NT$", _cur_ccy],
                    horizontal=True,
                    key=f"q_amt_ccy_{used_sym}",
                    label_visibility="collapsed",
                )
            else:
                _amt_ccy = "NT$"

            if _amt_ccy == "NT$":
                _est = q_price * q_shares * (_fx_to_twd if _is_foreign else 1)
                _amt_input = st.number_input(
                    "台幣總額（含手續費）", min_value=0.0,
                    value=float(_est), step=100.0, format="%.0f",
                    key=f"q_twd_{used_sym}",
                )
                q_twd_input = _amt_input
            else:
                _est = q_price * q_shares
                _amt_input = st.number_input(
                    f"{_cur_ccy} 總額（含手續費）", min_value=0.0,
                    value=float(_est), step=1.0, format="%.4f",
                    key=f"q_native_{used_sym}",
                )
                # 換算回 TWD 存進 DB
                q_twd_input = _amt_input * (_fx_to_twd or 0)
    else:
        with f2:
            if _is_foreign:
                _in_ccy = st.radio(
                    "輸入幣別",
                    ["NT$", _cur_ccy],
                    horizontal=True,
                    key=f"q_in_ccy_{used_sym}",
                    label_visibility="collapsed",
                )
            else:
                _in_ccy = "NT$"

            if _in_ccy == "NT$":
                _in_amt = st.number_input(
                    "台幣金額", min_value=0.0,
                    value=0.0, step=1000.0, format="%.0f",
                    key=f"q_twd_amt_{used_sym}",
                    help="輸入實際扣款台幣金額",
                )
                if q_price > 0 and _in_amt > 0:
                    if _cur_ccy == "TWD":
                        q_shares = _in_amt / q_price
                    elif _fx_to_twd:
                        fx_twd_to_native = _cached_fx("TWD", _cur_ccy)
                        q_shares = (_in_amt * fx_twd_to_native / q_price) if fx_twd_to_native else 0
                    else:
                        q_shares = 0
                else:
                    q_shares = 0
                q_twd_input = _in_amt
            else:
                _in_amt = st.number_input(
                    f"{_cur_ccy} 金額", min_value=0.0,
                    value=0.0, step=10.0, format="%.4f",
                    key=f"q_native_amt_{used_sym}",
                    help=f"輸入實際扣款 {_cur_ccy} 金額",
                )
                q_shares = _in_amt / q_price if q_price > 0 and _in_amt > 0 else 0
                q_twd_input = _in_amt * (_fx_to_twd or 0)

        f3.text_input(
            "自動算出股數",
            value=f"{q_shares:,.4f} 股" if q_shares > 0 else "—",
            disabled=True,
            key=f"q_sh_calc_{used_sym}",
        )

    q_note = st.text_input(
        "備註（選填）", placeholder="如：第3次補倉 / 定期定額 / 碎股",
        key=f"q_note_{used_sym}",
    )

    b1, b2 = st.columns(2)
    buy_clicked = b1.button(
        "🟢  記錄買進", type="primary",
        width="stretch", key=f"q_buy_{used_sym}",
    )
    sell_clicked = b2.button(
        "🔴  記錄賣出",
        width="stretch", key=f"q_sell_{used_sym}",
    )
    st.caption("💡 單價鎖定 = 當前市價；需要記錄歷史成交價請到「📒 帳務」新增交易")

    if buy_clicked or sell_clicked:
        if q_price <= 0:
            st.error("請填入單價")
        elif q_shares <= 0:
            if _input_mode == "依股數":
                st.error("請填入股數")
            else:
                st.error("請填入台幣金額（且匯率須可取得）")
        else:
            from datetime import date as _date_today
            try:
                add_transaction(
                    symbol=used_sym,
                    action="buy" if buy_clicked else "sell",
                    trade_date=_date_today.today().isoformat(),
                    price=float(q_price),
                    shares=float(q_shares),
                    twd_amount=float(q_twd_input) if q_twd_input > 0 else None,
                    currency=_cur_ccy,
                    note=q_note or "",
                )
                _msg = (
                    f"已記錄：{'買進' if buy_clicked else '賣出'} {used_sym} × {q_shares:,.4f} @ "
                    f"{q_price:,.4f} {_cur_ccy}  ·  NT${q_twd_input:,.0f}  → 已同步到帳務"
                )
                # 把訊息存進 session_state，下次 render 時顯示（避免 rerun 立即清掉）
                st.session_state[_last_ok_key] = _msg
                # 清空 input（單價已鎖死為現價，不需清；幣別 radio 也保留）
                for _k in (f"q_sh_{used_sym}", f"q_twd_{used_sym}",
                           f"q_twd_amt_{used_sym}", f"q_native_{used_sym}",
                           f"q_native_amt_{used_sym}", f"q_note_{used_sym}"):
                    if _k in st.session_state:
                        del st.session_state[_k]
                st.rerun()
            except Exception as e:
                st.error(f"寫入失敗：{e}")


st.divider()


# ── Summary cards ──────────────────────────────
c1, c2, c3, c4 = st.columns(4)

_grade_color = {"green": "#2ecc71", "blue": "#3498db", "orange": "#f39c12", "red": "#e74c3c"}

with c1:
    st.plotly_chart(score_gauge(fund_result["total_score"], "基本面評分"), width="stretch")
    _col = _grade_color.get(fund_result["color"], "white")
    st.markdown(f"<div style='text-align:center;color:{_col};font-weight:600;margin-top:-12px'>{fund_result['grade']}</div>", unsafe_allow_html=True)

with c2:
    risk_score = 100 - risk_result["risk_score"]
    st.plotly_chart(score_gauge(risk_score, "穩定性評分"), width="stretch")
    _col = _grade_color.get(risk_result["color"], "white")
    st.markdown(f"<div style='text-align:center;color:{_col};font-weight:600;margin-top:-12px'>{risk_result['level']}</div>", unsafe_allow_html=True)

with c3:
    st.plotly_chart(score_gauge(val_result["valuation_score"], "估值合理度"), width="stretch")
    _col = _grade_color.get(val_result["color"], "white")
    _label = f"{val_result['status']} — {val_result['suggestion']}"
    st.markdown(f"<div style='text-align:center;color:{_col};font-weight:600;margin-top:-12px;font-size:0.85rem'>{_label}</div>", unsafe_allow_html=True)

with c4:
    action = pos_result["action"]
    action_color = pos_result["action_color"]
    st.markdown(f"""
    <div style='text-align:center; padding:30px 0'>
        <div style='font-size:1.1rem; color:#aaa;'>建議操作</div>
        <div style='font-size:2.5rem; font-weight:700; color:{action_color};'>{action}</div>
        <div style='font-size:0.9rem; margin-top:8px;'>{pos_result['strategy']}</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()


# ── Tabs ───────────────────────────────────────
tab_chart, tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs([
    "價格走勢", "A 基本面", "B 風險", "C 估值", "D 資金配置", "E 建倉策略"
])


# Tab: Price chart
with tab_chart:
    fig = price_chart(data["history"], used_sym)
    st.plotly_chart(fig, width="stretch")
    if ma200_bias is not None:
        bias_color = "green" if ma200_bias < -15 else "red" if ma200_bias > 15 else "blue"
        st.metric(
            "MA200 乖離率",
            f"{ma200_bias:+.2f}%",
            help="(股價 - MA200) / MA200 × 100%",
        )


# Tab A: Fundamental
with tab_a:
    st.subheader(f"基本面評分：{fund_result['total_score']:.1f} / 100 — {fund_result['grade']}")

    if fund_result.get("is_etf"):
        st.info(f"ETF評估：{fund_result.get('etf_summary', '')}")
    else:
        st.plotly_chart(fundamental_bar(fund_result["details"]), width="stretch")

        rows = []
        for k, (score, max_s, desc) in fund_result["details"].items():
            rows.append({"指標": k, "得分": score, "滿分": max_s, "說明": desc})
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)


# Tab B: Risk
with tab_b:
    st.subheader(f"風險等級：{risk_result['level']} — {risk_result['description']}")

    rows = []
    for k, v in risk_result["metrics"].items():
        rows.append({"指標": k, "數值": v["value"], "風險分數": v["risk_pts"], "說明": v["note"]})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# Tab C: Valuation
with tab_c:
    st.subheader(f"估值狀態：{val_result['status']} — {val_result['suggestion']}")

    rows = []
    for k, v in val_result["metrics"].items():
        rows.append({"指標": k, "數值": v["value"], "合理度得分": v["score_pts"], "說明": v["note"]})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if ma200_bias is not None:
        st.info(f"均線乖離率公式：(股價 − MA200) / MA200 × 100% = **{ma200_bias:+.2f}%**")


# Tab D: Allocation
with tab_d:
    st.subheader("本月資金配置建議")

    _ccy = alloc_result["stock_currency"]
    _fx = alloc_result.get("fx_rate")
    _is_foreign = _fx is not None and _ccy not in ("TWD", "")

    # FX info banner
    if _is_foreign and _fx:
        st.info(
            f"預算以新台幣輸入，依即時匯率換算：**1 TWD = {_fx:.5f} {_ccy}**　"
            f"（NT${alloc_result['twd_budget']:,.0f} ≈ {_ccy} {alloc_result['monthly_budget']:,.2f}）"
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        primary = f"NT${alloc_result['twd_invest']:,.0f}"
        secondary = f"{_ccy} {alloc_result['invest_amount']:,.2f}" if _is_foreign else ""
        st.metric("本月投入", primary, f"{alloc_result['invest_ratio']*100:.0f}%")
        if secondary:
            st.caption(f"≈ {secondary}")
    with col2:
        primary = f"NT${alloc_result['twd_reserve']:,.0f}"
        secondary = f"{_ccy} {alloc_result['cash_reserve']:,.2f}" if _is_foreign else ""
        st.metric("保留現金", primary, f"{alloc_result['cash_ratio']*100:.0f}%")
        if secondary:
            st.caption(f"≈ {secondary}")
    with col3:
        st.metric("月總預算", f"NT${alloc_result['twd_budget']:,.0f}")

    col_chart, col_info = st.columns([1, 2])
    with col_chart:
        st.plotly_chart(allocation_pie(alloc_result["invest_ratio"], alloc_result["cash_ratio"]), width="stretch")
    with col_info:
        st.markdown(f"**投入時機：** {alloc_result['schedule']}")
        if alloc_result["extra_buy"]:
            st.warning("MA200乖離超過 -20%：建議額外補倉機會")
        st.markdown("**決策依據：**")
        for r in alloc_result["rationale"]:
            st.markdown(f"- {r}")
        st.caption("📌 MA200（200日移動平均線）：將過去200個交易日的收盤價平均，反映股票長期趨勢。股價高於MA200代表多頭趨勢，乖離率越大表示漲幅越過熱；低於MA200則可能是低估買點。")


# Tab E: Position
with tab_e:
    st.subheader(f"建倉策略：{pos_result['action']}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**策略說明：** {pos_result['strategy']}")
        st.markdown(f"**分批建議：** {pos_result['batch_suggestion']}")
        st.markdown(f"**最大倉位：** 不超過總資產 {pos_result['max_position_pct']}")

    with col2:
        _topic_for_send = get_topic()
        if pos_result["add_triggered"]:
            st.success("補倉訊號觸發")
            if _topic_for_send:
                if st.button("🔔 發送補倉通知", key="send_add_notify", width="stretch"):
                    _title, _body = build_message(used_sym, "add", full_result)
                    _ok, _detail = send(_body, _topic_for_send, title=_title, tags="bell")
                    if _ok:
                        st.toast("補倉通知已送出 🔔", icon="✅")
                    else:
                        st.error(f"發送失敗：{_detail}")
            else:
                st.caption("（未設定 ntfy 主題）")
        if pos_result["reduce_triggered"]:
            st.warning("減碼訊號觸發")
            if _topic_for_send:
                if st.button("⚠️ 發送減碼通知", key="send_reduce_notify", width="stretch"):
                    _title, _body = build_message(used_sym, "reduce", full_result)
                    _ok, _detail = send(_body, _topic_for_send, title=_title,
                                        priority="high", tags="warning")
                    if _ok:
                        st.toast("減碼通知已送出 ⚠️", icon="✅")
                    else:
                        st.error(f"發送失敗：{_detail}")
            else:
                st.caption("（未設定 ntfy 主題）")

    if pos_result["rules"]:
        st.markdown("**觸發規則：**")
        for r in pos_result["rules"]:
            st.markdown(f"- {r}")

    # Reference table
    st.divider()
    st.markdown("**補倉/減倉條件參考**")
    ref_data = {
        "情境": ["持倉下跌 -10%（基本面未惡化）", "持倉下跌 -20%+", "估值過熱", "基本面惡化", "MA200乖離 > +20%"],
        "操作": ["啟動補倉", "強力補倉", "分批減碼 20%", "停止加碼，考慮出清", "暫停加碼"],
    }
    st.dataframe(pd.DataFrame(ref_data), width="stretch", hide_index=True)

st.divider()
st.caption(f"分析時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}　資料來源：Yahoo Finance　本工具僅供參考，不構成投資建議。")
