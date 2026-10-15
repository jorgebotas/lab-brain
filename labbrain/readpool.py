"""Concurrent file reads with ordered results and a bounded number in flight.

Reads mostly wait on the disk and on on-access (antivirus) scanners, so a few
threads overlap that waiting with parsing in the calling thread. Results come back
in input order, so callers keep their deterministic ordering.
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def read_workers() -> int:
    """Threads for concurrent file reads."""
    return min(8, os.cpu_count() or 4)


def ordered_map(fn: Callable[[T], R], items: Iterable[T]) -> Iterator[R]:
    """`fn(item)` for each item, run in worker threads, yielded in input order.

    At most 2 x read_workers() calls are in flight or finished-but-unconsumed, so
    memory stays bounded however slowly the caller consumes. If the caller stops
    early (an exception, or closing the generator), pending calls are cancelled and
    the pool shuts down without waiting for reads still running. Use it with
    ``contextlib.closing`` so that happens at once rather than at garbage collection.
    """
    workers = read_workers()
    pending = iter(items)
    window: deque[Future[R]] = deque()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        for item in pending:
            window.append(pool.submit(fn, item))
            if len(window) >= 2 * workers:
                break
        while window:
            result = window.popleft().result()
            for item in pending:  # top up the window by one
                window.append(pool.submit(fn, item))
                break
            yield result
    finally:
        for future in window:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
