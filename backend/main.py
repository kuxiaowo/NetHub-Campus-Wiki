"""Campus Wiki 后端 API 服务。

后端职责：
- 提供 REST API。
- 读取 MySQL 数据并整理响应结构。
- 暴露 OpenAPI 文档。

后端不再托管前端页面；前端由 frontend_server.py 单独提供静态服务。
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import get_db_connection
from backend.projects import get_project, list_meta, list_projects
from backend.schemas import (
    AnnouncementsResponse,
    HealthResponse,
    MetaResponse,
    ProjectDetailResponse,
    ProjectListResponse,
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
        {"name": "content", "description": "首页内容接口。"},
        {"name": "projects", "description": "CAS 项目库查询接口。"},
    ],
)

# 前后端分离后，浏览器会从 3200 端口访问 3100 端口 API，因此需要 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
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


@app.get("/api/announcements", response_model=AnnouncementsResponse, tags=["content"])
def announcements():
    """返回首页公告。

    当前公告先放在内存常量里，后续如果需要后台管理，可以迁移到 announcements 表。
    """

    return {"data": ANNOUNCEMENTS}


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
