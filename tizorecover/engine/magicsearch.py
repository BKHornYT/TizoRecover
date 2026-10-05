"""Find every file magic in a chunk, on several CPU cores when there are some.

The deep scan's hot loop is one regex over each 8 MiB chunk for all ~64
magics. Python's ``re`` holds the GIL and slows down as the number of
distinct first bytes grows, so with the full format list it ran at ~55 MB/s
on one core. Here the chunk is copied once into shared memory and helper
processes each search one slice of it; the result is the exact list a single
``finditer`` over the whole chunk would give (same hits, same order), so the
carver above it cannot tell the difference.

Anything going wrong with the helpers (no cores, a frozen app started without
``freeze_support``, a helper killed) falls back to the plain search for the
rest of the run. ``TIZO_CARVE_WORKERS=0`` turns the helpers off.
"""

from __future__ import annotations

import atexit
import os
import re
import sys
import threading
from multiprocessing import get_context, shared_memory

from tizorecover.engine.formats import BY_MAGIC, MAX_MAGIC as _MAX_FORMAT_MAGIC
from tizorecover.engine.fs.ntfs import RECORD_MAGICS

# Below this a chunk is searched in-process: shipping it costs more than it saves.
PARALLEL_MIN = 1 << 20
MAX_WORKERS = 6


def _trie_pattern(words: list[bytes]) -> bytes:
    """One regex shaped like a prefix tree of the magics.

    Python's ``re`` tries the branches of a flat alternation one by one at
    every byte; factoring the shared prefixes lets it rule out most positions
    on the first byte (~35% faster over real data, same hits).
    """
    trie: dict = {}
    for word in words:
        node = trie
        for b in word:
            node = node.setdefault(b, {})
        node[None] = True

    def build(node: dict) -> bytes:
        alts = [re.escape(bytes([b])) + build(child)
                for b, child in sorted((k, v) for k, v in node.items() if k is not None)]
        if not alts:
            return b""
        body = alts[0] if len(alts) == 1 else b"(?:" + b"|".join(alts) + b")"
        return b"(?:" + body + b")?" if None in node else body

    return build(trie)


# File-system records the deep scan also wants to hear about (see carver's on_record).
EXTRA_MAGICS = tuple(RECORD_MAGICS)
ALL_MAGICS = list(BY_MAGIC) + [m for m in EXTRA_MAGICS if m not in BY_MAGIC]
MAX_MAGIC = max(_MAX_FORMAT_MAGIC, *(len(m) for m in EXTRA_MAGICS))
MAGIC_RE = re.compile(_trie_pattern(ALL_MAGICS))


def _search(buf, start: int, stop: int) -> list[tuple[int, int]]:
    """(start, end) of every magic beginning in ``[start, stop)``.

    A magic that begins before ``stop`` is at most ``MAX_MAGIC`` long, so
    letting the regex see that far past ``stop`` gives it the whole magic.
    """
    hits = []
    for m in MAGIC_RE.finditer(buf, start, min(stop + MAX_MAGIC - 1, len(buf))):
        if m.start() >= stop:
            break
        hits.append(m.span())
    return hits


def search_serial(buf) -> list[tuple[int, int]]:
    return [m.span() for m in MAGIC_RE.finditer(buf)]


# --- helper process side ----------------------------------------------------

_attached: dict[str, shared_memory.SharedMemory] = {}


def _worker_search(name: str, length: int, start: int, stop: int) -> list[tuple[int, int]]:
    shm = _attached.get(name)
    if shm is None:
        for old in _attached.values():
            old.close()
        _attached.clear()
        shm = _attached[name] = shared_memory.SharedMemory(name=name)
    view = shm.buf[:length]
    try:
        return _search(view, start, stop)
    finally:
        view.release()


# --- scan side ----------------------------------------------------------------

def _worker_count() -> int:
    env = os.environ.get("TIZO_CARVE_WORKERS")
    if env is not None:
        try:
            return max(0, int(env))
        except ValueError:
            pass
    cores = os.cpu_count() or 1
    return min(MAX_WORKERS, cores - 1) if cores >= 3 else 0


class _Helpers:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pool = None
        self.shm: shared_memory.SharedMemory | None = None
        self.workers = _worker_count()
        self.broken = self.workers < 2

    def _start(self, size: int) -> None:
        if self.pool is None:
            from concurrent.futures import ProcessPoolExecutor
            # spawn everywhere: forking a process that runs the UI server's
            # threads is unsafe, and Windows can only spawn anyway.
            self.pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=get_context("spawn"))
        if self.shm is None or self.shm.size < size:
            self._drop_shm()
            self.shm = shared_memory.SharedMemory(create=True, size=size)

    def _drop_shm(self) -> None:
        if self.shm is not None:
            try:
                self.shm.close()
                self.shm.unlink()
            except Exception:
                pass
            self.shm = None

    def search(self, buf) -> list[tuple[int, int]] | None:
        if self.broken or len(buf) < PARALLEL_MIN or not self.lock.acquire(blocking=False):
            return None                                  # a second scan at once searches on its own
        try:
            n = len(buf)
            self._start(max(n, 8 << 20))
            self.shm.buf[:n] = buf
            step = -(-n // self.workers)
            bounds = [(a, min(a + step, n)) for a in range(0, n, step)]
            futures = [self.pool.submit(_worker_search, self.shm.name, n, a, b) for a, b in bounds]
            parts = [f.result() for f in futures]
        except Exception as exc:
            self.broken = True
            print(f"tizorecover: parallel search off ({exc!r}), searching on one core", file=sys.stderr)
            self.close()
            return None
        finally:
            self.lock.release()
        return _merge(buf, bounds, parts)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
        self._drop_shm()


def _merge(buf, bounds, parts) -> list[tuple[int, int]]:
    """Stitch the slices together exactly as one ``finditer`` would see them.

    ``finditer`` never returns overlapping matches: after a magic it carries
    on from that magic's end. If the last magic of one slice runs into the
    next slice, that next slice's own search started too early, so it is
    redone on one core from the right place (rare: a magic straddling a seam).
    """
    out: list[tuple[int, int]] = []
    last_end = 0
    for (a, b), part in zip(bounds, parts):
        if part and part[0][0] < last_end:
            part = _search(buf, last_end, b) if last_end < b else []
        for span in part:
            out.append(span)
            last_end = span[1]
    return out


_helpers: _Helpers | None = None
_helpers_lock = threading.Lock()


def find_magics(buf) -> list[tuple[int, int]]:
    """(start, end) of every magic in ``buf``, in order, non-overlapping."""
    global _helpers
    if len(buf) >= PARALLEL_MIN:
        if _helpers is None:
            with _helpers_lock:
                if _helpers is None:
                    _helpers = _Helpers()
        got = _helpers.search(buf)
        if got is not None:
            return got
    return search_serial(buf)


@atexit.register
def _shutdown() -> None:
    if _helpers is not None:
        _helpers.close()
