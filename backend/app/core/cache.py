"""해석 결과 TTL 캐시.

resolve 와 다운로드가 **같은** 캐시를 쓴다. 이게 핵심이다 — 예전에는 작업마다
인스타 GraphQL 을 다시 호출해서(페이지 fetch → ruling → graphql) 버튼을 누르고
2~4초를 그냥 기다렸다. 방금 해석한 결과를 재사용하면 그 시간이 사라진다.

담고 있는 CDN 주소는 서명·만료가 붙어 있으므로 무한정 재사용할 수 없다. 그래서
(1) TTL 을 짧게 두고 (2) 받다가 실패하면 캐시를 버리고 한 번 다시 추출한다.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """작은 LRU-ish TTL 캐시. 워커 스레드에서도 쓰이므로 락을 둔다."""

    def __init__(self, limit: int = 64) -> None:
        self._entries: dict[str, tuple[float, T]] = {}
        self._limit = limit
        self._lock = Lock()

    def get(self, key: str, max_age: float) -> T | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.time() - stored_at > max_age:
                self._entries.pop(key, None)
                return None
            return value

    def put(self, key: str, value: T) -> None:
        with self._lock:
            if key not in self._entries and len(self._entries) >= self._limit:
                oldest = min(self._entries, key=lambda k: self._entries[k][0])
                self._entries.pop(oldest, None)
            self._entries[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# MediaInfo 캐시 — resolve 와 다운로드가 공유한다
media_cache: TTLCache = TTLCache()
