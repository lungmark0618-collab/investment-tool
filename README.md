# 長期投資決策工具

基本面 × 風險 × 估值 × 資金配置 × 建倉策略，一站式長期投資輔助工具。

## 功能

- **單檔分析**：6 大模組（基本面 10 項 + 風險 5 項 + 估值 6 項 + 資金配置 + 建倉策略 + 大盤狀態）
- **多標配置**：依基本面/風險/估值自動加權，產生組合配置
- **帳務記錄**：交易日記 + FIFO 持倉計算 + 交易日曆熱圖
- **快速下單**：在分析頁直接記錄買賣（依股數 / 依台幣金額 / 支援碎股）
- **搜尋**：用名稱（中英文）或代碼都能查到股票
- **大盤判定**：S&P 500 + VIX 綜合判斷牛熊市，逆向調整資金乘數
- **自動掃描**：Windows 工作排程器每日掃描自選清單，觸發訊號推播
- **ntfy.sh 推播**：補倉/減碼訊號自動推到手機

## 安裝

```bash
pip install -r requirements.txt
```

## 啟動

```bash
python -m streamlit run app.py --server.port 8501
```

## 架構

- `app.py` — Streamlit 主程式
- `modules/` — 5 大分析模組（fundamental / risk / valuation / allocation / position / portfolio / market_regime）
- `utils/` — 工具（data_fetcher / notifier / scheduler / search / glossary）
- `database/` — SQLite 持久化（analysis_history / watchlist / transactions / notification_log）
- `scan_watchlist.py` — 背景掃描腳本（給 Windows 工作排程器使用）

## 資料來源

Yahoo Finance（yfinance）

## 免責聲明

本工具僅供參考，不構成投資建議。
