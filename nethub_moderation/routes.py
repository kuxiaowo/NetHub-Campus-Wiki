"""Authenticated site endpoints and server-side proxy to the shared worker."""

import hmac
import os
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from .policy import CATEGORIES


def internal_auth(request: Request):
    token = os.environ.get("MODERATION_TOKEN", "")
    expected = "Bearer " + token
    if (
        len(token) < 32
        or request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or not hmac.compare_digest(request.headers.get("authorization", ""), expected)
    ):
        raise HTTPException(403, "内部审核接口禁止访问")


async def proxy(method, path, payload=None):
    url = os.environ.get("MODERATION_SERVICE_URL", "http://127.0.0.1:3500").rstrip("/")
    parts = urlsplit(url)
    if parts.hostname not in {"127.0.0.1", "::1"} or parts.scheme != "http":
        raise HTTPException(503, "共享审核服务必须配置为本机地址")
    token = os.environ.get("MODERATION_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "共享审核服务待配置")
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=620) as client:
            response = await client.request(
                method,
                url + path,
                json=payload,
                headers={"Authorization": "Bearer " + token},
            )
    except httpx.HTTPError:
        raise HTTPException(503, "共享审核服务暂时不可用") from None
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", "审核服务请求失败")
        except ValueError:
            detail = "审核服务请求失败"
        raise HTTPException(response.status_code, detail)
    return response.json()


def make_router(site, admin_dependency, user_dependency):
    router = APIRouter()

    @router.get("/api/admin/moderation/categories")
    def categories(_: dict = Depends(admin_dependency)):
        return {"categories": CATEGORIES, "other": "其他"}

    @router.get("/api/admin/moderation/cases")
    def cases(
        state: str = Query(
            "review", pattern="^(review|failed|history|queued|dispatch|running)$"
        ),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, alias="pageSize", ge=1, le=50),
        _: dict = Depends(admin_dependency),
    ):
        return site.cases(state, page, page_size)

    @router.post("/api/admin/moderation/cases/{case_id}/decision")
    def decision(
        case_id: int, payload: dict = Body(...), admin: dict = Depends(admin_dependency)
    ):
        try:
            site.decide(
                case_id,
                admin["id"],
                payload.get("action"),
                payload.get("reasons", []),
                payload.get("note", ""),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"ok": True}

    @router.post("/api/admin/moderation/cases/{case_id}/retry")
    def retry(case_id: int, _: dict = Depends(admin_dependency)):
        try:
            site.retry(case_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"ok": True}

    @router.post("/api/admin/moderation/comments/{comment_id}/delete")
    def delete(
        comment_id: int,
        payload: dict = Body(...),
        admin: dict = Depends(admin_dependency),
    ):
        try:
            site.delete(
                comment_id,
                admin["id"],
                payload.get("reasons", []),
                payload.get("note", ""),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"ok": True}

    @router.get("/api/admin/moderation/settings")
    async def settings(_: dict = Depends(admin_dependency)):
        return await proxy("GET", "/settings")

    @router.patch("/api/admin/moderation/settings")
    async def save(payload: dict = Body(...), _: dict = Depends(admin_dependency)):
        return await proxy("PATCH", "/settings", payload)

    @router.post("/api/admin/moderation/models")
    async def models(
        payload: dict = Body(default={}), _: dict = Depends(admin_dependency)
    ):
        return await proxy("POST", "/models", payload)

    @router.post("/api/admin/moderation/test")
    async def test(
        payload: dict = Body(default={}), _: dict = Depends(admin_dependency)
    ):
        return await proxy("POST", "/test", payload)

    @router.get("/api/admin/moderation/status")
    async def status(_: dict = Depends(admin_dependency)):
        try:
            worker = await proxy("GET", "/status")
        except HTTPException as exc:
            worker = {"ready": False, "message": str(exc.detail)}
        return {**worker, "queue": site.counts()}

    @router.post("/api/admin/moderation/codex/login")
    async def login(_: dict = Depends(admin_dependency)):
        return await proxy("POST", "/codex/login", {})

    @router.get("/api/system-notifications")
    def notifications(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, alias="pageSize", ge=1, le=50),
        user: dict = Depends(user_dependency),
    ):
        return site.notifications(user["id"], page, page_size)

    @router.post("/api/system-notifications/read")
    def read(payload: dict = Body(...), user: dict = Depends(user_dependency)):
        through = payload.get("throughId")
        if type(through) is not int or through < 0:
            raise HTTPException(422, "throughId 无效")
        site.read(user["id"], through)
        return {"ok": True}

    @router.post("/internal/moderation/claim", dependencies=[Depends(internal_auth)])
    def claim(payload: dict = Body(...)):
        return {
            "job": site.claim(
                int(payload.get("version", 0)),
                max(10, min(600, int(payload.get("timeout", 180)))),
            )
        }

    @router.post("/internal/moderation/result", dependencies=[Depends(internal_auth)])
    def result(payload: dict = Body(...)):
        try:
            applied = site.complete(
                payload["job"],
                payload.get("result"),
                payload.get("error", ""),
                payload.get("retryAt"),
            )
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "审核结果无效") from None
        return {"applied": applied}

    return router
