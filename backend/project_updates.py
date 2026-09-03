"""Authenticated CAS project update publishing routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.admin import create_project_update_record, delete_project_update_record
from backend.auth import get_current_user
from backend.database import get_db_connection
from backend.projects import (
    decorate_project_for_viewer,
    get_project,
    project_update_publisher,
)
from backend.schemas import ProjectDetailResponse


router = APIRouter(prefix="/api/projects", tags=["projects"])
MAX_MEMBER_UPDATE_CONTENT_LENGTH = 2000
MAX_MEMBER_UPDATE_PHOTOS = 9


def _require_project_update_publisher(
    project_id: int,
    user: dict[str, Any],
) -> dict[str, Any]:
    publisher = project_update_publisher(project_id, user)
    if publisher is not None:
        return publisher

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s LIMIT 1", (project_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="项目不存在")
    raise HTTPException(status_code=403, detail="只有已绑定账号的项目成员才能管理动态")


def _project_detail_response(project_id: int, user: dict[str, Any]) -> dict[str, Any]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"data": decorate_project_for_viewer(project, user)}


@router.post("/{project_id}/updates", response_model=ProjectDetailResponse)
async def create_member_project_update(
    project_id: int,
    content: str = Form(default=""),
    photos: list[UploadFile] | None = File(default=None),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Allow a bound project member (or an admin) to publish an update."""

    publisher = _require_project_update_publisher(project_id, user)
    clean_content = content.strip()
    uploads = photos or []
    if len(clean_content) > MAX_MEMBER_UPDATE_CONTENT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"动态内容不能超过 {MAX_MEMBER_UPDATE_CONTENT_LENGTH} 个字符",
        )
    if len(uploads) > MAX_MEMBER_UPDATE_PHOTOS:
        raise HTTPException(
            status_code=422,
            detail=f"每条动态最多上传 {MAX_MEMBER_UPDATE_PHOTOS} 张照片",
        )

    await create_project_update_record(
        project_id,
        clean_content,
        "[]",
        uploads,
        publisher,
    )
    return _project_detail_response(project_id, user)


@router.delete("/{project_id}/updates/{update_id}", response_model=ProjectDetailResponse)
def delete_member_project_update(
    project_id: int,
    update_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Delete an own update, or any project update as leader/admin."""

    publisher = _require_project_update_publisher(project_id, user)
    delete_project_update_record(project_id, update_id, publisher)
    return _project_detail_response(project_id, user)
