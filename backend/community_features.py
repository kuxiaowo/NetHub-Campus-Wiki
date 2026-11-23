"""Read the public switches from Accounts before serving community operations."""

import requests
from fastapi import APIRouter, HTTPException, Response

from backend.config import settings

router = APIRouter(prefix="/api", tags=["community"])


def fetch_features():
    url = settings.community_features_url or settings.oidc_issuer + "/api/community-features"
    response = requests.get(
        url,
        timeout=3,
        allow_redirects=False,
        headers={"Accept": "application/json", "User-Agent": "NetHub-Campus-Wiki/1.0"},
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Unexpected community settings response")
    return response.json()


def community_features():
    try:
        data = fetch_features()
    except (requests.RequestException, ValueError):
        data = {}
    return {key: isinstance(data, dict) and data.get(key) is True for key in ("comments", "messages")}


def require_comments():
    if not community_features()["comments"]:
        raise HTTPException(403, "评论已暂停")


def require_messages():
    if not community_features()["messages"]:
        raise HTTPException(403, "私信已暂停")


@router.get("/community-features")
def public_features(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return community_features()
