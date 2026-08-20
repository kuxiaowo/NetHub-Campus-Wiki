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


class User(BaseModel):
    """登录用户信息。"""

    id: int
    username: str
    displayName: str | None = None
    role: str = Field(pattern="^(admin|user)$")
    isActive: bool
    createdAt: datetime | None = None


class PublicUser(BaseModel):
    """私信和成员关联场景可公开使用的精简用户信息。"""

    id: int
    username: str
    displayName: str | None = None


class UserSearchResponse(BaseModel):
    data: list[PublicUser]


class UserProfileProject(BaseModel):
    """用户在一个 CAS 项目中的公开身份。"""

    id: int
    name: str
    category: str
    year: int
    memberName: str
    memberRole: str = Field(pattern="^(leader|member)$")


class UserProfile(PublicUser):
    projects: list[UserProfileProject]


class UserProfileResponse(BaseModel):
    data: UserProfile


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
    """CAS 项目成员；即使尚未关联注册账号也会独立存在。"""

    id: int
    displayName: str
    role: str = Field(pattern="^(leader|member)$")
    sortOrder: int
    user: PublicUser | None = None


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
                "memberProfiles": [
                    {
                        "id": 1,
                        "displayName": "李明",
                        "role": "leader",
                        "sortOrder": 0,
                        "user": None,
                    }
                ],
                "category": "科技创新",
                "year": 2026,
                "icon": "https://picsum.photos/seed/noise-map-icon/300/300",
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
    memberProfiles: list[ProjectMember]
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


class ConversationCreateRequest(BaseModel):
    userId: int = Field(gt=0)


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class DirectMessage(BaseModel):
    id: int
    conversationId: int
    senderId: int
    content: str
    createdAt: datetime | None = None
    readAt: datetime | None = None
    isMine: bool


class ConversationSummary(BaseModel):
    id: int
    otherUser: PublicUser
    lastMessage: DirectMessage | None = None
    unreadCount: int
    updatedAt: datetime | None = None


class ConversationListResponse(BaseModel):
    data: list[ConversationSummary]


class ConversationResponse(BaseModel):
    data: ConversationSummary


class MessageListResponse(BaseModel):
    data: list[DirectMessage]


class MessageResponse(BaseModel):
    data: DirectMessage


class UnreadCountResponse(BaseModel):
    unreadCount: int


class ResourceCategory(BaseModel):
    """资源分类筛选项。"""

    value: str = Field(description="分类值，用于查询参数。")
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
    category: str
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
