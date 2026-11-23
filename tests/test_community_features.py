from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest
import requests

from backend import comments, community_features, messaging


def test_closed_operations_and_independent_switches(monkeypatch):
    flags = {"comments": False, "messages": False}
    monkeypatch.setattr(community_features, "fetch_features", lambda: flags)
    app = FastAPI()
    for router in (comments.router, messaging.router, community_features.router):
        app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/community-features").json() == flags
    for method, path in [
        ("get", "/comments"), ("post", "/comments"), ("get", "/comments/1/context"),
        ("post", "/comments/1/like"), ("get", "/comment-notifications"),
        ("get", "/conversations"), ("post", "/conversations/1/messages"),
        ("get", "/conversations/1/messages"), ("post", "/messages/stream-ticket"),
    ]:
        assert client.request(method, "/api" + path).status_code == 403
    flags["comments"] = True
    community_features.require_comments()
    assert client.get("/api/conversations").status_code == 403
    flags.update(messages=True, comments=False)
    community_features.require_messages()
    assert client.get("/api/comments").status_code == 403
    app.dependency_overrides[messaging.get_current_user] = lambda: {"id": 2}
    ticket = client.post("/api/messages/stream-ticket").json()["ticket"]
    with client.websocket_connect("/api/messages/ws?ticket=" + ticket) as socket:
        flags["messages"] = False
        socket.send_text("ping")
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4403


def test_missing_or_unavailable_settings_pause_both(monkeypatch):
    def unavailable():
        raise requests.Timeout()
    for source in (unavailable, lambda: {"comments": "true", "messages": 1}, lambda: None):
        monkeypatch.setattr(community_features, "fetch_features", source)
        assert community_features.community_features() == {"comments": False, "messages": False}
