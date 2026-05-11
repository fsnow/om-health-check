"""Parallel execution helpers for per-host check work.

Each check section that loops over hosts uses ``parallel_host_check`` to
fan out the per-host work across a thread pool. HTTP is I/O-bound so threads
are appropriate (no GIL concern). Results are returned in input order so the
report is deterministic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# Module-level state set once at start of each run.
_max_workers: int = 10


def set_max_workers(n: int) -> None:
    """Override the default thread-pool size used by per-section parallelism."""
    global _max_workers
    _max_workers = max(1, int(n))


def get_max_workers() -> int:
    return _max_workers


def parallel_host_check(fn: Callable[[T], R], items: List[T]) -> List[R]:
    """Apply ``fn`` to each item concurrently; return results in input order.

    Falls back to a serial loop when max_workers == 1 to keep tracebacks clean
    in single-thread debug mode.
    """
    workers = min(_max_workers, len(items)) if items else 1
    if workers <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(fn, items))
