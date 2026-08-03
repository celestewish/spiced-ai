"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    created_at: datetime


class TeamCreate(BaseModel):
    name: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_by: str
    created_at: datetime


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    user_id: str | None
    invited_email: str | None
    role: str
    joined_at: datetime | None
    created_at: datetime


class TeamInviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class TeamProjectCreate(BaseModel):
    project_uuid: str
    name: str


class TeamProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    project_uuid: str
    name: str
    created_at: datetime
