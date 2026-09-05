"""Campus Wiki 后端 API 服务。

后端职责：
- 提供 REST API。
- 读取 SQLite 数据并整理响应结构。
- 暴露 OpenAPI 文档。

后端不再托管前端页面；前端由 frontend_server.py 单独提供静态服务。
"""

from contextlib import asynccontextmanager
from html import escape
import mimetypes
import re
import sys
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import uvicorn

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.admin import router as admin_router
from backend.announcements import router as announcements_router
from backend.comments import router as comments_router
from backend.messaging import router as messaging_router
from backend.project_updates import router as project_updates_router
from backend.social import router as social_router
from backend.config import settings, validate_runtime_settings
from backend.auth import (
    SESSION_COOKIE_NAME,
    authenticate_user,
    change_user_password,
    create_access_token,
    create_session,
    create_user,
    get_current_user,
    get_current_user_from_token,
    get_optional_current_user,
    provision_oidc_user,
    revoke_session,
    revoke_sessions,
    update_username,
)
from backend.auth_rate_limit import (
    clear_login_failures,
    enforce_login_request,
    enforce_password_change_request,
    enforce_register_request,
    record_login_failure,
)
from backend.database import get_db_connection
from backend.oidc_client import (
    OIDC_STATE_COOKIE,
    OidcClientError,
    begin_login,
    complete_login,
    validate_logout_token,
)
from backend.media import PUBLIC_MEDIA_EXTENSIONS
from backend.projects import decorate_project_for_viewer, get_project, list_meta, list_projects
from backend.resources import (
    YearbookResourceError,
    bump_photo_activity_downloads,
    bump_resource_metric,
    get_activity_photo_detail,
    get_resource,
    get_yearbook_detail,
    list_photo_activities,
    list_resource_meta,
    list_resources,
)
from backend.schemas import (
    ChangePasswordRequest,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MetaResponse,
    PhotoActivityListResponse,
    PhotoActivityDetailResponse,
    PhotoActivityPhotosResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ResourceListResponse,
    ResourceDetailResponse,
    ResourceMetaResponse,
    RegisterRequest,
    UpdateCurrentUserRequest,
    User,
    YearbookDetailResponse,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动即校验安全配置，避免服务带着弱密钥监听端口。"""

    validate_runtime_settings()
    yield


# FastAPI 实例集中声明接口元信息，/docs 会根据这些内容生成接口文档。
app = FastAPI(
    title="Campus Wiki API",
    description=(
        "校园论坛与 CAS 项目库后端 API。后端只负责数据接口和数据库访问，"
        "前端由独立静态服务提供。"
    ),
    version="1.1.0",
    lifespan=lifespan,
    contact={"name": "Campus Wiki Team"},
    openapi_tags=[
        {"name": "system", "description": "服务状态与运行信息。"},
        {"name": "auth", "description": "用户注册、登录和当前用户接口。"},
        {"name": "content", "description": "首页内容接口。"},
        {"name": "projects", "description": "CAS 项目库查询接口。"},
        {"name": "resources", "description": "资源中心和活动照片查询接口。"},
        {"name": "social", "description": "用户资料、关注、黑名单和管理员维护的人员账号绑定。"},
        {"name": "messages", "description": "一对一私信、动态限流和实时消息。"},
        {"name": "announcements", "description": "公告列表、详情和后台维护。"},
        {"name": "comments", "description": "公告、项目和资源共用留言区。"},
    ],
)

# 前后端分离后，浏览器会从 3200 端口访问 3100 端口 API，因此需要 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(admin_router)
app.include_router(project_updates_router)
app.include_router(social_router)
app.include_router(messaging_router)
app.include_router(announcements_router)
app.include_router(comments_router)


BASE_DIR = Path(__file__).resolve().parents[1]
PUBLIC_DIR = BASE_DIR / "public"
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:/")


@app.middleware("http")
async def cookie_session_security(request: Request, call_next):
    """Apply Origin-based CSRF protection and baseline response headers."""

    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path != "/api/auth/backchannel-logout"
        and request.cookies.get(SESSION_COOKIE_NAME)
    ):
        origin = request.headers.get("origin", "")
        if origin not in settings.cors_origins:
            return HTMLResponse("CSRF origin validation failed", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/auth"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def _resolve_public_file(file_path: str) -> Path:
    raw_path = file_path.strip().replace("\\", "/").lstrip("/")
    path = Path(raw_path)
    if not raw_path or path.is_absolute() or path.drive or ".." in path.parts or WINDOWS_DRIVE_PATTERN.match(raw_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    public_root = PUBLIC_DIR.resolve()
    target = (public_root / raw_path).resolve()
    if target != public_root and public_root not in target.parents and target != public_root:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


def _get_file_request_user(request: Request) -> dict:
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        return get_current_user_from_token(cookie)
    if not settings.oidc_client_secret:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            return get_current_user_from_token(authorization.split(" ", 1)[1].strip())

        token = request.query_params.get("token")
        if token:
            return get_current_user_from_token(token)

    raise HTTPException(status_code=401, detail="需要登录")


@app.api_route("/media/{file_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def public_media_file(file_path: str):
    """Serve public images and video directly from the backend host."""

    target = _resolve_public_file(file_path)
    if target.suffix.casefold() not in PUBLIC_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=300",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/files/{file_path:path}", tags=["resources"])
def protected_public_file(file_path: str, request: Request):
    """Serve files from public/ only to logged-in users."""

    _get_file_request_user(request)
    target = _resolve_public_file(file_path)
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health():
    """健康检查接口：确认 API 进程和数据库连接是否可用。"""

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # 只执行最轻量的 SELECT 1，用来验证数据库连接和账号权限。
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
        return {"ok": True, "database": "connected"}
    except Exception as exc:  # noqa: BLE001 - development diagnostics are intentional here.
        return {"ok": False, "message": "数据库连接失败", "detail": str(exc)}


@app.post("/api/auth/register", response_model=User, tags=["auth"])
def register(payload: RegisterRequest, request: Request):
    """Legacy local registration; disabled whenever OIDC is configured."""

    if settings.oidc_client_secret:
        raise HTTPException(status_code=410, detail="本地注册已关闭，请使用 NetHub Accounts")

    enforce_register_request(request)
    return create_user(
        username=payload.username,
        password=payload.password,
        display_name=payload.displayName,
    )


@app.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login(payload: LoginRequest, request: Request):
    """Legacy local login; disabled whenever OIDC is configured."""

    if settings.oidc_client_secret:
        raise HTTPException(status_code=410, detail="本地密码登录已关闭，请使用 NetHub Accounts")

    rate_config = enforce_login_request(request, payload.username)
    try:
        user = authenticate_user(payload.username, payload.password)
    except HTTPException as error:
        if error.status_code == 401:
            record_login_failure(payload.username, rate_config)
        raise
    clear_login_failures(payload.username)
    return {"accessToken": create_access_token(user), "tokenType": "bearer", "user": user}


@app.get("/api/auth/me", response_model=User, tags=["auth"])
def current_user(user: dict = Depends(get_current_user)):
    """Return the local member bound to the current HttpOnly session."""

    return user


@app.patch("/api/auth/me", response_model=User, tags=["auth"])
def update_current_user(payload: UpdateCurrentUserRequest, user: dict = Depends(get_current_user)):
    """修改当前登录用户的昵称。"""

    return update_username(user_id=user["id"], username=payload.username)


@app.patch("/api/auth/password", response_model=User, tags=["auth"])
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """修改当前登录用户密码，必须提供原密码。"""

    if settings.oidc_client_secret:
        raise HTTPException(status_code=410, detail="密码请在 NetHub Accounts 修改")

    enforce_password_change_request(request, user["id"])
    return change_user_password(
        user_id=user["id"],
        current_password=payload.currentPassword,
        new_password=payload.newPassword,
    )


@app.get("/api/auth/login", tags=["auth"])
def oidc_login(return_to: str | None = Query(default=None, alias="returnTo")):
    """Start Authorization Code + PKCE at NetHub Accounts."""

    try:
        authorization_url, state = begin_login(return_to)
    except OidcClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        OIDC_STATE_COOKIE,
        state,
        max_age=600,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/api/auth",
    )
    return response


@app.get("/api/auth/callback", tags=["auth"])
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Validate the provider response, provision a member and set a local session."""

    if error:
        return HTMLResponse("账号中心拒绝了本次登录，请返回后重试。", status_code=400)
    if not code or not state:
        return HTMLResponse("登录回调缺少 code 或 state，请重新登录。", status_code=400)
    try:
        identity = complete_login(
            code,
            state,
            request.cookies.get(OIDC_STATE_COOKIE, ""),
        )
        user = provision_oidc_user(
            auth_sub=identity["sub"],
            preferred_username=identity["preferred_username"],
            display_name=identity["name"],
        )
        token = create_session(user["id"], auth_sub=identity["sub"], sid=identity["sid"])
    except OidcClientError as exc:
        return HTMLResponse(f"登录未完成：{escape(str(exc))}", status_code=502)
    except HTTPException as exc:
        return HTMLResponse(
            f"登录未完成：{escape(str(exc.detail))}", status_code=exc.status_code
        )
    response = RedirectResponse(identity["return_to"], status_code=303)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/api/auth")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.auth_session_absolute_seconds,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@app.post("/api/auth/logout", tags=["auth"])
def local_logout(request: Request):
    """Delete only the current Wiki session; central SSO remains active."""

    revoke_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@app.post("/api/auth/backchannel-logout", tags=["auth"])
def backchannel_logout(logout_token: str = Form(...)):
    """Revoke matching Wiki sessions after a signed Accounts notification."""

    try:
        claims = validate_logout_token(logout_token)
    except OidcClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    revoked = revoke_sessions(
        auth_sub=str(claims["sub"]) if claims.get("sub") else None,
        sid=str(claims["sid"]) if claims.get("sid") else None,
    )
    return {"ok": True, "revoked": revoked}


@app.get("/api/meta", response_model=MetaResponse, tags=["projects"])
def meta():
    """返回项目库筛选器需要的分类和年份。"""

    return list_meta()


@app.get("/api/projects", response_model=ProjectListResponse, tags=["projects"])
def projects(
    category: str | None = Query(default=None, description="按项目分类筛选。"),
    year: int | None = Query(default=None, description="按项目年份筛选。"),
    search: str | None = Query(default=None, description="搜索项目名称、负责人和简介。"),
    sort: str = Query(default="latest", pattern="^(latest|popular)$", description="排序方式：latest 或 popular。"),
):
    """返回项目列表。

    前端项目库页面会把分类、年份、搜索词和排序方式转换为查询参数传入这里。
    """

    return {"data": list_projects(category=category, year=year, search=search, sort=sort)}


@app.get("/api/projects/{project_id}", response_model=ProjectDetailResponse, tags=["projects"])
def project_detail(
    project_id: int,
    track: bool = Query(default=True, description="是否计入前台浏览热度。"),
    user: dict | None = Depends(get_optional_current_user),
):
    """返回单个项目详情。"""

    project = get_project(
        project_id,
        track_view=track,
        viewer_user_id=user["id"] if user else None,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"data": decorate_project_for_viewer(project, user)}


@app.get("/api/resources/meta", response_model=ResourceMetaResponse, tags=["resources"])
def resources_meta():
    """返回资源中心筛选器需要的分类和年份。"""

    return list_resource_meta()


@app.get("/api/resources", response_model=ResourceListResponse, tags=["resources"])
def resources(
    category: Literal["yearbook", "teacher", "other"] | None = Query(default=None, description="按资源分类筛选。"),
    year: int | None = Query(default=None, description="按资源年份筛选。"),
    search: str | None = Query(default=None, description="搜索资源名称、简介和分类。"),
    sort: str = Query(default="hot", pattern="^(hot|new|old|download)$", description="排序方式。"),
):
    """返回资源中心普通资源列表。"""

    return {"data": list_resources(category=category, year=year, search=search, sort=sort)}


@app.get("/api/resources/{resource_id}", response_model=ResourceDetailResponse, tags=["resources"])
def resource_detail(
    resource_id: int,
    track: bool = Query(default=True, description="是否计入前台浏览热度。"),
    user: dict | None = Depends(get_optional_current_user),
):
    resource = get_resource(
        resource_id,
        track_view=track,
        viewer_user_id=user["id"] if user else None,
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return {"data": resource}


@app.get("/api/resources/{resource_id}/yearbook", response_model=YearbookDetailResponse, tags=["resources"])
def resource_yearbook(
    resource_id: int,
    track: bool = Query(default=True, description="是否计入前台浏览热度。"),
    user: dict | None = Depends(get_optional_current_user),
):
    """返回单个 Yearbook 资源目录下的图片页面和 PDF 下载地址。"""

    try:
        return {
            "data": get_yearbook_detail(
                resource_id,
                track_view=track,
                viewer_user_id=user["id"] if user else None,
            )
        }
    except YearbookResourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/resources/{resource_id}/download", response_model=ResourceDetailResponse, tags=["resources"])
def resource_download(resource_id: int, user: dict = Depends(get_current_user)):
    """给资源下载数加一，并返回更新后的资源。"""

    resource = bump_resource_metric(resource_id, "downloads")
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return {"data": resource}


@app.get("/api/photo-activities", response_model=PhotoActivityListResponse, tags=["resources"])
def photo_activities(
    year: int | None = Query(default=None, description="按活动年份筛选。"),
    search: str | None = Query(default=None, description="搜索活动名称。"),
    sort: str = Query(default="hot", pattern="^(hot|new|old|photoCount|download)$", description="排序方式。"),
):
    """返回活动照片活动列表，不包含完整照片数组。"""

    return {"data": list_photo_activities(year=year, search=search, sort=sort)}


@app.post("/api/photo-activities/{activity_id}/download", response_model=PhotoActivityDetailResponse, tags=["resources"])
def photo_activity_download(activity_id: int, user: dict = Depends(get_current_user)):
    """Increment one activity archive download counter and return the updated activity."""

    activity = bump_photo_activity_downloads(activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return {"data": activity}


@app.get("/api/photo-activities/{activity_id}/photos", response_model=PhotoActivityPhotosResponse, tags=["resources"])
def photo_activity_photos(
    activity_id: int,
    track: bool = Query(default=True, description="是否计入前台浏览热度。"),
    user: dict | None = Depends(get_optional_current_user),
):
    """返回单个活动下的照片。"""

    detail = get_activity_photo_detail(
        activity_id,
        track_view=track,
        viewer_user_id=user["id"] if user else None,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return {"data": detail["photos"], "activity": detail["activity"]}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )
