# 工作規則（給 Claude / Cowork）

## Git 流程
- **改完就直接 commit + push 到 origin/main**，不要等使用者提醒
- commit message 用中文，描述「為什麼改」而非「改了什麼」
- 任何敏感檔案絕對不能提交（password / token / secrets）

## 已 gitignore 的個人資料
- `data/config.json`（ntfy topic、設定）
- `data/investment.db`（本機 SQLite，雲端用 Supabase）
- `data/scan.log`
- `.streamlit/secrets.toml`（含 Supabase DATABASE_URL）
- `*password*.txt`、`*secret*.txt`、`*credentials*.txt`、`*.pem`、`*.key`

## 部署
- 主分支：`main`
- Streamlit Cloud 連結：`mark-investment-tool.streamlit.app`（或實際 URL）
- 推上 GitHub 後 Streamlit Cloud 會自動重新部署

## 測試
- 改完用 `streamlit.testing.v1.AppTest` 驗證關鍵流程後再 push
- 本機開發跑 `python -m streamlit run app.py`（port 8501）

## 不要做的事
- 不要建空 commit、不要 `git push --force` 到 main
- 不要動 `.streamlit/secrets.toml`（內含 Supabase 認證）
- 不要把 secrets 寫入程式碼或 README
