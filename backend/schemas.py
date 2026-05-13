"""API 响应模型。

Pydantic 模型用于三件事：
- 约束接口返回结构，避免字段随意变化。
- 自动生成 OpenAPI 文档。
- 给后续维护者明确前后端之间的数据契约。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """健康检查响应。"""

    ok: bool = Field(description="API 服务是否可用。")
    database: str | None = Field(default=None, description="数据库连接成功时的状态。")
    message: str | None = Field(default=None, description="面向开发者的错误说明。")
    detail: str | None = Field(default=None, description="更具体的诊断信息。")


class AnnouncementsResponse(BaseModel):
    """首页公告响应。"""

    data: list[str] = Field(description="公告文本列表。")


class MetaResponse(BaseModel):
    """项目筛选元数据响应。"""

    categories: list[str] = Field(description="可筛选的项目分类。")
    years: list[int] = Field(description="可筛选的项目年份。")


class CasFlags(BaseModel):
    """CAS 三项标记。"""

    creativity: bool = Field(description="是否包含 Creativity。")
    activity: bool = Field(description="是否包含 Activity。")
    service: bool = Field(description="是否包含 Service。")


class Project(BaseModel):
    """项目对象。

    字段名保持前端友好，使用 createdAt/updatedAt，而不是数据库里的 created_at。
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "name": "校园噪音地图",
                "leader": "李明",
                "members": "李明, 王小雨, Chen Alex",
                "category": "科技创新",
                "year": 2026,
                "icon": "🗺️",
                "description": "使用传感器采集校园不同地点的噪音数据。",
                "media": ["https://picsum.photos/seed/noise-map/900/520"],
                "cas": {"creativity": True, "activity": True, "service": True},
                "popularity": 96,
                "updates": ["完成第一版传感器数据模拟器"],
                "createdAt": "2026-05-10T10:00:00",
                "updatedAt": "2026-05-10T10:00:00",
            }
        }
    )

    id: int
    name: str
    leader: str
    members: str
    category: str
    year: int
    icon: str
    description: str
    media: list[str]
    cas: CasFlags
    popularity: int
    updates: list[str]
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class ProjectListResponse(BaseModel):
    """项目列表响应。"""

    data: list[Project] = Field(description="符合查询条件的项目列表。")


class ProjectDetailResponse(BaseModel):
    """项目详情响应。"""

    data: Project = Field(description="指定 ID 的项目。")
