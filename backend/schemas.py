"""API 响应模型。

Pydantic 模型用于三件事：
- 约束接口返回结构，避免字段随意变化。
- 自动生成 OpenAPI 文档。
- 给后续维护者明确前后端之间的数据契约。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """健康检查响应。"""

    ok: bool = Field(description="API 服务是否可用。")
    database: str | None = Field(default=None, description="数据库连接成功时的状态。")
    message: str | None = Field(default=None, description="面向开发者的错误说明。")
    detail: str | None = Field(default=None, description="更具体的诊断信息。")


class User(BaseModel):
    """登录用户信息。"""

    id: int
    username: str
    displayName: str | None = None
    avatarUrl: str | None = None
    bio: str = ""
    role: str = Field(pattern="^(admin|user)$")
    isActive: bool
    campusVerified: bool = False
    messagingPermission: str = Field(
        default="everyone",
        pattern="^(everyone|following|mutual|nobody)$",
    )
    linkedPersonId: int | None = None
    createdAt: datetime | None = None


class RegisterRequest(BaseModel):
    """用户注册请求。"""

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8)
    displayName: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    """用户登录请求。"""

    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    """当前用户修改密码请求。"""

    currentPassword: str
    newPassword: str = Field(min_length=8)


class UpdateCurrentUserRequest(BaseModel):
    """当前用户资料更新请求。"""

    username: str = Field(min_length=3, max_length=32)


class LoginResponse(BaseModel):
    """登录成功响应。"""

    accessToken: str
    tokenType: str = "bearer"
    user: User


class MetaResponse(BaseModel):
    """项目筛选元数据响应。"""

    categories: list[str] = Field(description="可筛选的项目分类。")
    years: list[int] = Field(description="可筛选的项目年份。")


class CasFlags(BaseModel):
    """CAS 三项标记。"""

    creativity: bool = Field(description="是否包含 Creativity。")
    activity: bool = Field(description="是否包含 Activity。")
    service: bool = Field(description="是否包含 Service。")


class ProjectMember(BaseModel):
    """结构化 CAS 项目成员。"""

    personId: int
    name: str
    role: str = Field(pattern="^(leader|member)$")
    avatarUrl: str | None = None
    userId: int | None = None
    username: str | None = None
    registered: bool = False
    sortOrder: int = 0
    contactType: str | None = Field(default=None, pattern="^(wechat|phone|email|other)$")
    contactValue: str | None = None


class ProjectUpdate(BaseModel):
    """一条可携带独立照片的 CAS 项目动态。"""

    content: str = ""
    images: list[str] = Field(default_factory=list)


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
                "icon": "https://picsum.photos/seed/noise-map-icon/300/300",
                "description": "使用传感器采集校园不同地点的噪音数据。",
                "media": [],
                "cas": {"creativity": True, "activity": True, "service": True},
                "popularity": 96,
                "updates": [
                    {
                        "content": "完成第一版传感器数据模拟器",
                        "images": ["https://picsum.photos/seed/noise-map/900/520"],
                    }
                ],
                "createdAt": "2026-05-10T10:00:00",
                "updatedAt": "2026-05-10T10:00:00",
            }
        }
    )

    id: int
    name: str
    leader: str
    members: str
    memberList: list[ProjectMember] = Field(default_factory=list)
    category: str
    year: int
    icon: str | None = None
    description: str
    media: list[str]
    cas: CasFlags
    popularity: int
    updates: list[str | ProjectUpdate]
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class ProjectListResponse(BaseModel):
    """项目列表响应。"""

    data: list[Project] = Field(description="符合查询条件的项目列表。")


class ProjectDetailResponse(BaseModel):
    """项目详情响应。"""

    data: Project = Field(description="指定 ID 的项目。")


class ResourceCategory(BaseModel):
    """资源分类筛选项。"""

    value: Literal["yearbook", "photos", "teacher", "other"] = Field(description="固定分类值，用于查询参数。")
    label: str = Field(description="分类展示名称。")
    sortOrder: int = Field(description="人工排序权重，数字越小越靠前。")


class ResourceMetaResponse(BaseModel):
    """资源中心筛选元数据响应。"""

    categories: list[ResourceCategory] = Field(description="可筛选的资源分类。")
    years: list[int] = Field(description="可筛选的资源年份。")
    photoYears: list[int] = Field(description="可筛选的照片活动年份。")


class Resource(BaseModel):
    """资源中心普通资源对象。"""

    id: int
    title: str
    description: str
    year: int
    category: Literal["yearbook", "teacher", "other"]
    label: str
    hot: int
    downloads: int
    image: str
    resourceUrl: str
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class ResourceListResponse(BaseModel):
    """资源列表响应。"""

    data: list[Resource] = Field(description="符合查询条件的资源列表。")


class ResourceDetailResponse(BaseModel):
    """单个资源响应。"""

    data: Resource


class YearbookPage(BaseModel):
    """Yearbook image page discovered from a resource directory."""

    index: int
    title: str
    src: str
    thumbSrc: str | None = None


class YearbookDetail(BaseModel):
    """Yearbook reader data for one resource."""

    resource: Resource
    pages: list[YearbookPage]
    pdfUrl: str | None = None


class YearbookDetailResponse(BaseModel):
    """Yearbook reader response."""

    data: YearbookDetail


class PhotoItem(BaseModel):
    """单张活动照片。"""

    id: int
    title: str
    src: str
    thumbSrc: str | None = None
    sortOrder: int


class PhotoActivity(BaseModel):
    """活动照片活动摘要。"""

    id: int
    activity: str
    description: str
    year: int
    hot: int
    downloads: int = 0
    sortOrder: int
    photoDir: str | None = None
    archiveUrl: str | None = None
    coverSrc: str | None = None
    coverThumbSrc: str | None = None
    photoCount: int
    createdAt: datetime | None = None


class PhotoActivityListResponse(BaseModel):
    """活动照片列表响应。"""

    data: list[PhotoActivity] = Field(description="符合查询条件的活动照片集合。")


class PhotoActivityDetailResponse(BaseModel):
    """单个活动照片摘要响应。"""

    data: PhotoActivity


class PhotoActivityPhotosResponse(BaseModel):
    """单个活动照片响应。"""

    data: list[PhotoItem] = Field(description="指定活动下的照片集合。")
    activity: PhotoActivity | None = Field(default=None, description="更新热度后的活动摘要。")
