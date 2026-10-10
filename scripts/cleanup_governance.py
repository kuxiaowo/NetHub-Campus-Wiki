"""Daily private media and governance retention cleanup using configured storage."""

import json
import logging

import requests

from backend.content_review import delete_private_image, site
from backend.media_storage import MediaStorageError

logger = logging.getLogger(__name__)


def cleanup():
    # Writers cannot add images to withdrawn/rejected submissions; public images
    # are retained even when referenced by an administrator's imported project.
    with site.db() as db:
        candidates = [
            dict(row)
            for row in db.execute("""
        SELECT m.* FROM _private_content_media m JOIN _private_content_submissions s ON s.id=m.submission_id
        WHERE s.status IN ('withdrawn','rejected') AND s.updated_at<datetime('now','-30 days')
        AND NOT EXISTS(SELECT 1 FROM project_updates p,json_each(p.images) image WHERE image.value='/api/content-media/'||m.id)
        """)
        ]
    deleted, failed = 0, 0
    for row in candidates:
        try:
            delete_private_image(row["storage_key"])
        except (requests.RequestException, MediaStorageError, OSError, ValueError):
            logger.warning("Private media cleanup failed for id=%s", row["id"])
            failed += 1
            continue
        with site.db(True) as db:
            db.execute("DELETE FROM _private_content_media WHERE id=?", (row["id"],))
        deleted += 1
    with site.db(True) as db:
        db.execute("""DELETE FROM _moderation_jobs WHERE state IN ('passed','dismissed','deleted','cancelled')
        AND updated_at<datetime('now','-180 days')""")
        db.execute("""UPDATE _moderation_content_jobs SET result_json='{}',error_code=''
        WHERE state IN ('passed','dismissed','cancelled') AND updated_at<datetime('now','-180 days')""")
        db.execute("""UPDATE _private_content_submissions SET content='',decision_note='',metadata='{}'
        WHERE status IN ('published','withdrawn','rejected') AND updated_at<datetime('now','-180 days')""")
        db.execute(
            "DELETE FROM governance_audit WHERE created_at<datetime('now','-365 days')"
        )
        db.execute(
            "UPDATE system_notifications SET original_excerpt='',reason_note='' WHERE created_at<datetime('now','-180 days')"
        )
        db.execute("""UPDATE governance_audit SET details='{}'
        WHERE action LIKE 'content.%' AND created_at<datetime('now','-180 days')""")
    return {"mediaDeleted": deleted, "mediaFailed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(cleanup()))
