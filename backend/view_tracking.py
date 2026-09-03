"""进程内浏览热度节流。

登录用户按对象节流；游客请求没有稳定身份，因此每次成功读取都计数。
"""

from __future__ import annotations

import time

from backend.config import settings

_TRACKED_VIEWS: dict[tuple[str, int, int], float] = {}


def can_track_view(scope: str, item_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return True
    previous = _TRACKED_VIEWS.get((scope, item_id, user_id))
    return previous is None or time.monotonic() - previous >= settings.resource_hot_throttle_seconds


def mark_view_tracked(scope: str, item_id: int, user_id: int | None) -> None:
    if user_id is not None:
        _TRACKED_VIEWS[(scope, item_id, user_id)] = time.monotonic()


def clear_tracked_views() -> None:
    """清空节流状态，供测试隔离使用。"""

    _TRACKED_VIEWS.clear()
