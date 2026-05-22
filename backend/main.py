"""Campus Wiki 后端 API 服务。

后端职责：
- 提供 REST API。
- 读取 MySQL 数据并整理响应结构。
- 暴露 OpenAPI 文档。

后端不再托管前端页面；前端由 frontend_server.py 单独提供静态服务。
"""

import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.admin import router as admin_router
from backend.config import settings
from backend.auth import authenticate_user, create_access_token, create_user, get_current_user
from backend.database import get_db_connection
from backend.projects import get_project, list_meta, list_projects
from backend.resources import list_photo_activities, list_resource_meta, list_resources
from backend.schemas import (
    AnnouncementsResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    MetaResponse,
    PhotoActivityListResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ResourceListResponse,
    ResourceMetaResponse,
    RegisterRequest,
    User,
)

ANNOUNCEMENTS = [
    "CAS 项目库原型上线：欢迎提交你的项目资料。",
    "本周五 16:00 将举办 CAS 项目分享会。",
    "项目展示页已支持照片/视频链接和动态更新。",
]

# FastAPI 实例集中声明接口元信息，/docs 会根据这些内容生成接口文档。
app = FastAPI(
    title="Campus Wiki API",
    description=(
        "校园论坛与 CAS 项目库后端 API。后端只负责数据接口和数据库访问，"
        "前端由独立静态服务提供。"
    ),
    version="1.1.0",
    contact={"name": "Campus Wiki Team"},
    openapi_tags=[
        {"name": "system", "description": "服务状态与运行信息。"},
        {"name": "auth", "description": "用户注册、登录和当前用户接口。"},
        {"name": "content", "description": "首页内容接口。"},
        {"name": "projects", "description": "CAS 项目库查询接口。"},
        {"name": "resources", "description": "资源中心和活动照片查询接口。"},
    ],
)

# 前后端分离后，浏览器会从 3200 端口访问 3100 端口 API，因此需要 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(admin_router)


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


@app.get("/api/announcements", response_model=AnnouncementsResponse, tags=["content"])
def announcements():
    """返回首页公告。

    当前公告先放在内存常量里，后续如果需要后台管理，可以迁移到 announcements 表。
    """

    return {"data": ANNOUNCEMENTS}


@app.post("/api/auth/register", response_model=User, tags=["auth"])
def register(payload: RegisterRequest):
    """开放注册普通用户，注册后的默认角色为 user。"""

    return create_user(
        username=payload.username,
        password=payload.password,
        display_name=payload.displayName,
    )


@app.post("/api/auth/login", response_model=LoginResponse, tags=["auth"])
def login(payload: LoginRequest):
    """使用用户名和密码登录，返回 Bearer Token。"""

    user = authenticate_user(payload.username, payload.password)
    return {"accessToken": create_access_token(user), "tokenType": "bearer", "user": user}


@app.get("/api/auth/me", response_model=User, tags=["auth"])
def current_user(user: dict = Depends(get_current_user)):
    """返回当前 Bearer Token 对应的用户。"""

    return user


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
def project_detail(project_id: int):
    """返回单个项目详情。"""

    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"data": project}


@app.get("/api/resources/meta", response_model=ResourceMetaResponse, tags=["resources"])
def resources_meta():
    """返回资源中心筛选器需要的分类和年份。"""

    return list_resource_meta()


@app.get("/api/resources", response_model=ResourceListResponse, tags=["resources"])
def resources(
    category: str | None = Query(default=None, description="按资源分类筛选。"),
    year: int | None = Query(default=None, description="按资源年份筛选。"),
    search: str | None = Query(default=None, description="搜索资源名称、简介和类型。"),
    sort: str = Query(default="hot", pattern="^(hot|new|old|download)$", description="排序方式。"),
):
    """返回资源中心普通资源列表。"""

    return {"data": list_resources(category=category, year=year, search=search, sort=sort)}


@app.get("/api/photo-activities", response_model=PhotoActivityListResponse, tags=["resources"])
def photo_activities(
    year: int | None = Query(default=None, description="按活动年份筛选。"),
    search: str | None = Query(default=None, description="搜索活动名称。"),
    sort: str = Query(default="hot", pattern="^(hot|new|old|photoCount)$", description="排序方式。"),
):
    """返回活动照片列表，每个活动包含自己的照片数组。"""

    return {"data": list_photo_activities(year=year, search=search, sort=sort)}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=True,
    )
