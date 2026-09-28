"""Wiki adapter for the shared moderation contracts."""

from backend.auth import get_current_user
from backend.comments import _require_admin
from backend.database import get_db_connection
from nethub_moderation.routes import make_router
from nethub_moderation.site import Site


def connect():
    facade = get_db_connection()
    if facade._connection is None:
        raise RuntimeError("评论审核需要 SQLite 在线数据库")
    return facade._connection


site = Site(connect, "wiki")
router = make_router(site, _require_admin, get_current_user)
