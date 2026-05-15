import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "investment.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                fundamental_score REAL,
                risk_level TEXT,
                valuation_status TEXT,
                invest_ratio REAL,
                recommendation TEXT,
                raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                added_at TEXT NOT NULL,
                note TEXT,
                cost_basis REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS notification_log (
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (symbol, signal_type)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,        -- 'buy' or 'sell'
                trade_date TEXT NOT NULL,    -- YYYY-MM-DD
                price REAL NOT NULL,          -- per-share price in native currency
                shares REAL NOT NULL,
                twd_amount REAL,              -- 台幣總額（用戶輸入或自動換算）
                currency TEXT DEFAULT 'TWD',
                note TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tx_symbol ON transactions(symbol);
            CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(trade_date);
        """)
        # backfill cost_basis column on existing dbs
        try:
            conn.execute("ALTER TABLE watchlist ADD COLUMN cost_basis REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass


def was_recently_notified(symbol: str, signal_type: str, hours: int = 24) -> bool:
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT notified_at FROM notification_log WHERE symbol=? AND signal_type=?",
            (symbol.upper(), signal_type),
        ).fetchone()
    if not row:
        return False
    try:
        last = datetime.fromisoformat(row["notified_at"])
    except Exception:
        return False
    return (datetime.now() - last).total_seconds() < hours * 3600


def log_notification(symbol: str, signal_type: str):
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notification_log (symbol, signal_type, notified_at) VALUES (?,?,?)",
            (symbol.upper(), signal_type, datetime.now().isoformat()),
        )


def set_watchlist_cost(symbol: str, cost_basis: float):
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE watchlist SET cost_basis=? WHERE symbol=?",
            (float(cost_basis), symbol.upper()),
        )


# ── Transactions ────────────────────────────────────────────────────────
def add_transaction(symbol: str, action: str, trade_date: str,
                    price: float, shares: float,
                    twd_amount: Optional[float] = None,
                    currency: str = "TWD",
                    note: str = ""):
    init_db()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO transactions
               (symbol, action, trade_date, price, shares, twd_amount, currency, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                symbol.upper(),
                action.lower(),
                trade_date,
                float(price),
                float(shares),
                float(twd_amount) if twd_amount is not None else None,
                currency,
                note,
                datetime.now().isoformat(),
            ),
        )


def get_transactions(symbol: Optional[str] = None) -> List[Dict]:
    init_db()
    with _get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE symbol=? ORDER BY trade_date DESC, id DESC",
                (symbol.upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY trade_date DESC, id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def delete_transaction(tx_id: int):
    init_db()
    with _get_conn() as conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (int(tx_id),))


def get_holdings() -> List[Dict]:
    """
    依交易紀錄推算目前持倉與加權平均成本。
    僅統計買進；賣出按 FIFO 扣除股數，剩餘股數的加權成本即為平均成本。
    """
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY symbol, trade_date, id"
        ).fetchall()
    txs_by_sym: Dict[str, List[Dict]] = {}
    for r in rows:
        txs_by_sym.setdefault(r["symbol"], []).append(dict(r))

    holdings = []
    for sym, txs in txs_by_sym.items():
        # FIFO lots
        lots: List[Dict] = []  # each: {shares, price, twd_cost}
        total_twd_invested = 0.0
        total_twd_realized = 0.0
        for tx in txs:
            if tx["action"] == "buy":
                lots.append({
                    "shares": tx["shares"],
                    "price": tx["price"],
                    "twd": tx.get("twd_amount") or 0,
                })
                total_twd_invested += tx.get("twd_amount") or 0
            else:  # sell
                remain = tx["shares"]
                proceeds = tx.get("twd_amount") or 0
                total_twd_realized += proceeds
                while remain > 0 and lots:
                    lot = lots[0]
                    if lot["shares"] <= remain:
                        remain -= lot["shares"]
                        lots.pop(0)
                    else:
                        # partial sell
                        ratio = remain / lot["shares"]
                        lot["shares"] -= remain
                        lot["twd"] *= (1 - ratio)
                        remain = 0

        if not lots:
            continue
        total_shares = sum(l["shares"] for l in lots)
        if total_shares <= 0:
            continue
        weighted_price = sum(l["shares"] * l["price"] for l in lots) / total_shares
        remaining_twd_cost = sum(l["twd"] for l in lots)

        holdings.append({
            "symbol": sym,
            "shares": total_shares,
            "avg_cost": weighted_price,
            "twd_cost": remaining_twd_cost,
            "twd_invested_total": total_twd_invested,
            "twd_realized": total_twd_realized,
            "currency": txs[-1].get("currency") or "TWD",
        })
    return holdings


def get_avg_cost(symbol: str) -> Optional[float]:
    """Convenience: 取某檔目前加權平均成本（原幣），無持倉回 None。"""
    for h in get_holdings():
        if h["symbol"] == symbol.upper():
            return h["avg_cost"]
    return None


def save_analysis(symbol: str, result: Dict[str, Any]):
    init_db()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO analysis_history
               (symbol, analyzed_at, fundamental_score, risk_level,
                valuation_status, invest_ratio, recommendation, raw_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                symbol.upper(),
                datetime.now().isoformat(),
                result.get("fundamental", {}).get("total_score"),
                result.get("risk", {}).get("level"),
                result.get("valuation", {}).get("status"),
                result.get("allocation", {}).get("invest_ratio"),
                result.get("position", {}).get("action"),
                json.dumps(result, ensure_ascii=False, default=str),
            ),
        )


def get_history(symbol: Optional[str] = None, limit: int = 20, unique_symbols: bool = False) -> List[Dict]:
    init_db()
    with _get_conn() as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM analysis_history WHERE symbol=? ORDER BY analyzed_at DESC LIMIT ?",
                (symbol.upper(), limit),
            ).fetchall()
        elif unique_symbols:
            rows = conn.execute(
                """SELECT * FROM analysis_history
                   WHERE id IN (SELECT MAX(id) FROM analysis_history GROUP BY symbol)
                   ORDER BY analyzed_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM analysis_history ORDER BY analyzed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def add_to_watchlist(symbol: str, note: str = ""):
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, added_at, note) VALUES (?,?,?)",
            (symbol.upper(), datetime.now().isoformat(), note),
        )


def get_watchlist() -> List[Dict]:
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_from_watchlist(symbol: str):
    init_db()
    with _get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol.upper(),))
