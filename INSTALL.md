# Shoryuken — daily run at 01:00 UAE

Copy **run_daily_scan.py** and **install_daily_scan.ps1** into:

`C:\Jupyter_project\shoryuken_project\shoryuken`

Keep your latest `shoryuken_scanner.ipynb` there. No project module or notebook replacement is needed.

## One-time installation

Run this cell in your existing working Jupyter notebook, after section 2 (so PROJECT_DIR is defined). This uses the same Python environment as your notebook:

```python
import sys, subprocess
subprocess.run([
    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", str(PROJECT_DIR / "install_daily_scan.ps1"),
    "-PythonExe", sys.executable,
    "-ProjectDir", str(PROJECT_DIR),
], check=True)
```

This installs nbclient/nbformat/ipykernel, registers a dedicated kernel, writes daily_scan_config.json, validates the notebook boundaries without running it, and registers **Shoryuken Daily Scan 0100 UAE** in Windows Task Scheduler. It does not start a full scan immediately. If the task already exists, installation stops; add `"-Replace"` to the argument list only when deliberately replacing that task.

## Manual full test

Run once while you are present:

```python
subprocess.run([
    sys.executable, str(PROJECT_DIR / "run_daily_scan.py"),
    "--config", str(PROJECT_DIR / "daily_scan_config.json"),
], check=True)
```

This is a real run: it performs your notebook's Yahoo requests and updates its normal caches/reports. It executes every code cell in sections 1 through 6b, including section 1's pip install, Yahoo diagnostic and scanner diagnostics. Section 7 onward and all backtests are excluded. Notebook source/output on disk is not overwritten. The latest saved notebook is read each time; save intended edits before the scheduled run. Failures stop execution rather than silently continuing.

## Daily behavior

- Trigger: **01:00 UAE (UTC+04:00), every day**, including weekends.
- Windows account must remain signed in; locking the screen is fine. Jupyter/browser can be closed.
- PC must be on or sleeping with wake timers permitted. Task requests wake; this is hardware/power-policy dependent. A fully shut down PC cannot run it. Missed starts run when available, while the account is signed in.
- The notebook runs with your supplied Python interpreter and project working directory, in a fresh kernel.
- Browser opening is disabled only in the execution copy. The final HTML is still generated normally.
- Existing trading rules, Qullamaggie cap settings in your Python modules, and Leaders code are used without modification. The notebook's metadata currently says $500M for Qullamaggie; that description is separate from the threshold you edited in qullamaggie_momentum.py. This runner does not alter either.
- Scheduled-task IgnoreNew plus an OS file lock prevents two instances of this runner. It does not prevent a separate manual Jupyter scan: avoid running those concurrently against the same files.
- Each cell has a 2-hour timeout; the task has a 12-hour maximum. An interrupted run may already have updated some caches/CSV exports. Normal notebook writes are not transactional across the entire run.
- A successful run means code executed and exported HTML, not that every Yahoo download succeeded or every price is fresh. Inspect data dates, fallback messages and coverage in the report. At 01:00 UAE, the latest completed US session depends on date and daylight-saving time.
- No email notifications or background task on ChatGPT are created.

## Where to look

`PROJECT_DIR\logs\scheduled\` contains dated:

- `.log`: cell progress, printed output and exceptions.
- `.ipynb`: executed copy, including rich results and any failed cell.
- `.json`: run status, interpreter, timing and executed-copy path.

HTML stays at the notebook's existing `Documents\Shoryuken_reports\all_scan_results.html` destination. Failed runs can leave the previous HTML there, so check status and file dates. The scheduler now uses logs: do not delete logs during a running job. Old dated logs/executed copies may be removed when no longer needed; there is no automatic retention deletion.

Open **Task Scheduler → Task Scheduler Library → Shoryuken Daily Scan 0100 UAE** to inspect, run, disable or delete the task. A nonzero Last Run Result means investigate the latest log. To run while signed out, configure the task's “Run whether user is logged on or not” option using Windows credentials locally; this installer intentionally stores no password and uses an interactive account.

## Validation limits

Prepared from the uploaded notebook with section 6b export at cell 27 and section 7 beginning at cell 28. Selection uses headings rather than those fixed positions; ambiguous/missing headings fail validation. Tests covered boundary selection, clearing outputs in the execution copy, preserving the original, project-path substitution and overlapping-run lock exclusion. No user notebook cells, Yahoo downloads, real project caches or reports were executed/modified during preparation. Windows task registration and live end-to-end execution must be tested on your Windows PC.
