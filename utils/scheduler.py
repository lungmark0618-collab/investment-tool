"""Windows Task Scheduler integration."""
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

TASK_PREFIX = "InvestmentScan_"
SCAN_SCRIPT = Path(__file__).parent.parent / "scan_watchlist.py"
PYTHON_EXE = sys.executable  # absolute path to current python


def _run(cmd: List[str]) -> Tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="cp950",
            errors="replace",
            timeout=30,
        )
        ok = out.returncode == 0
        return ok, (out.stdout + out.stderr).strip()
    except Exception as e:
        return False, str(e)


def list_tasks() -> List[str]:
    """List all installed InvestmentScan tasks."""
    ok, output = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    if not ok:
        return []
    tasks = []
    for line in output.splitlines():
        parts = [p.strip('"') for p in line.split(",")]
        if not parts:
            continue
        name = parts[0]
        # task names from schtasks are returned as "\TaskName"
        clean = name.lstrip("\\")
        if clean.startswith(TASK_PREFIX):
            tasks.append(clean)
    return sorted(set(tasks))


def install_tasks(times: List[str]) -> Tuple[bool, str]:
    """Create one daily task per time. Removes any existing InvestmentScan tasks first."""
    if not SCAN_SCRIPT.exists():
        return False, f"找不到掃描腳本：{SCAN_SCRIPT}"

    # cleanup existing
    uninstall_all()

    failures = []
    created = []
    for t in times:
        t = t.strip()
        if not t or ":" not in t:
            continue
        tag = t.replace(":", "")
        task_name = f"{TASK_PREFIX}{tag}"
        tr = f'"{PYTHON_EXE}" "{SCAN_SCRIPT}"'
        ok, msg = _run([
            "schtasks", "/Create",
            "/SC", "DAILY",
            "/ST", t,
            "/TN", task_name,
            "/TR", tr,
            "/F",
        ])
        if ok:
            created.append(task_name)
        else:
            failures.append(f"{task_name}: {msg}")

    if failures:
        return False, f"成功 {len(created)} 個 / 失敗 {len(failures)} 個\n" + "\n".join(failures)
    return True, f"已安裝 {len(created)} 個排程"


def uninstall_all() -> Tuple[bool, str]:
    """Remove all InvestmentScan_* tasks."""
    tasks = list_tasks()
    if not tasks:
        return True, "沒有需要移除的排程"
    failures = []
    for t in tasks:
        ok, msg = _run(["schtasks", "/Delete", "/TN", t, "/F"])
        if not ok:
            failures.append(f"{t}: {msg}")
    if failures:
        return False, "\n".join(failures)
    return True, f"已移除 {len(tasks)} 個排程"


def run_now() -> Tuple[bool, str]:
    """Run scan script once immediately (for manual testing)."""
    if not SCAN_SCRIPT.exists():
        return False, f"找不到掃描腳本：{SCAN_SCRIPT}"
    return _run([PYTHON_EXE, str(SCAN_SCRIPT)])
