"""Source file reader with mtime-aware TTL cache."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str
    lines: int
    mtime: float


class SourceService:
    def __init__(self, project_root: str, ttl_seconds: float):
        self._root = project_root
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, SourceFile]] = {}

    def read(self, rel_path: str) -> SourceFile:
        """Read a file under the project root. Rejects anything outside it."""
        abs_path = os.path.abspath(os.path.join(self._root, rel_path))
        root_abs = os.path.abspath(self._root)
        if not abs_path.startswith(root_abs + os.sep) and abs_path != root_abs:
            raise FileNotFoundError(rel_path)

        now = time.time()
        with self._lock:
            hit = self._cache.get(abs_path)
            if hit and (now - hit[0]) < self._ttl:
                try:
                    if os.path.getmtime(abs_path) == hit[1].mtime:
                        return hit[1]
                except OSError:
                    pass

        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        mtime = os.path.getmtime(abs_path)
        sf = SourceFile(
            path=rel_path,
            content=content,
            lines=content.count("\n") + (0 if content.endswith("\n") else 1),
            mtime=mtime,
        )
        with self._lock:
            self._cache[abs_path] = (time.time(), sf)
        return sf
