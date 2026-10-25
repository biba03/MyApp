"""
timing.py

Lightweight, opt-in timing instrumentation for the scan/research
pipeline - so future runs can show where time actually goes without
needing a full cProfile session every time.

Usage:

    from timing import timer, report, reset

    with timer("load_universe"):
        ...

    report()   # prints a sorted summary of total time per label
    reset()    # clears accumulated timings between independent runs

Design notes:
- Purely additive: timing never changes control flow or results, and
  adds negligible overhead (a couple of time.perf_counter() calls per
  timed block) - safe to leave enabled in production runs.
- Accumulates by label across multiple calls (e.g. every ticker's scan
  can share the label "scan_ticker" and you'll see the summed/average
  cost across all of them).
- Thread-safe for ThreadPoolExecutor-based scanning (a lock guards the
  shared accumulator).
- Multiprocessing workers each have their OWN copy of this module's
  state (no shared memory across processes) - timings recorded inside
  a ProcessPoolExecutor worker will NOT show up in the parent
  process's report(). Use sequential mode for detailed timing
  investigation.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager

_lock = threading.Lock()
_totals: dict[str, float] = defaultdict(float)
_counts: dict[str, int] = defaultdict(int)


def _record_elapsed(label: str, start: float) -> None:
    """
    Manual alternative to `timer()` for call sites where wrapping
    existing code in a `with` block would require re-indenting a
    large chunk of it:

        start = time.perf_counter()
        ... existing code, unchanged ...
        _record_elapsed("my_label", start)

    Accumulates into the same totals as `timer()`.
    """

    elapsed = time.perf_counter() - start

    with _lock:

        _totals[label] += elapsed

        _counts[label] += 1


@contextmanager
def timer(label: str):
    """
    Times the wrapped block and accumulates elapsed time under
    `label`. Safe to nest and safe to call from multiple threads.
    Records the time even if the wrapped code raises.
    """

    start = time.perf_counter()

    try:

        yield

    finally:

        elapsed = time.perf_counter() - start

        with _lock:

            _totals[label] += elapsed

            _counts[label] += 1


def reset() -> None:
    """Clears all accumulated timings."""

    with _lock:

        _totals.clear()

        _counts.clear()


def snapshot() -> dict[str, dict[str, float]]:
    """
    Current timings as {label: {"total", "count", "avg"}}, without
    printing - useful for tests or writing numbers to a file.
    """

    with _lock:

        return {
            label: {
                "total": _totals[label],
                "count": _counts[label],
                "avg": _totals[label] / _counts[label] if _counts[label] else 0.0,
            }
            for label in _totals
        }


def report(top_n: int | None = None) -> None:
    """Prints a summary table sorted by total time, descending."""

    data = snapshot()

    if not data:

        print("(no timings recorded - wrap code in `with timer(label):` first)")

        return

    rows = sorted(data.items(), key=lambda kv: kv[1]["total"], reverse=True)

    if top_n is not None:

        rows = rows[:top_n]

    width = max(len(label) for label, _ in rows)

    print(f"{'Label'.ljust(width)}  {'Total (s)':>10}  {'Count':>8}  {'Avg (s)':>10}")

    for label, stats in rows:

        print(
            f"{label.ljust(width)}  "
            f"{stats['total']:>10.3f}  {stats['count']:>8d}  {stats['avg']:>10.4f}"
        )
