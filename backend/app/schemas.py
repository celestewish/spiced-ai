"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    created_at: datetime


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    team_id: str | None
    plan_key: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    status: str
    current_period_end: datetime | None
    created_at: datetime


class CheckoutSessionCreate(BaseModel):
    plan_key: Literal["indie", "studio"]
    team_id: str | None = None


class CheckoutSessionOut(BaseModel):
    checkout_url: str


class PortalSessionOut(BaseModel):
    portal_url: str


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
    # Best-available contact address (pending invite address, or the joined
    # user's verified email) — see TeamMember.email. Added for Phase B's
    # Team Mode prompt context, which shows teammates by name/email.
    email: str | None
    role: str
    # Discipline/skill role (Phase J) -- see TeamMember.discipline. None
    # until the member (or another teammate) sets it.
    discipline: str | None = None
    joined_at: datetime | None
    created_at: datetime


class TeamInviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"
    # Optional owner-set discipline at invite time (Phase J, Role-Based
    # Dashboards) -- the invitee can still change it later via self-service.
    discipline: str | None = None


class MemberDisciplineUpdate(BaseModel):
    discipline: str | None = None


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


class SessionSummaryCreate(BaseModel):
    started_at: datetime
    ended_at: datetime
    summary_text: str


class SessionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    project_uuid: str
    user_id: str
    started_at: datetime
    ended_at: datetime
    summary_text: str
    created_at: datetime


class TelemetryEventCreate(BaseModel):
    anonymous_client_id: str
    event_name: str


class TelemetryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    anonymous_client_id: str
    event_name: str
    created_at: datetime


class PlayerCrashReportCreate(BaseModel):
    # These max_length caps are the outer bound Pydantic will accept at all
    # (a request over them is rejected with 422 before it's ever stored);
    # the router truncates further to the tighter, documented storage caps
    # (see routers.player_crashes) so the endpoint is never an open,
    # unbounded write even from a client that ignores these limits.
    error_type: str = Field(max_length=500)
    message: str = Field(max_length=4000)
    stack_excerpt: str | None = Field(default=None, max_length=20000)
    app_version: str | None = Field(default=None, max_length=200)
    occurred_at: datetime


class PlayerCrashReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_uuid: str
    error_type: str
    message: str
    stack_excerpt: str | None
    app_version: str | None
    occurred_at: datetime
    reported_at: datetime


class ChangelogEntryCreate(BaseModel):
    version_or_phase_label: str
    title: str
    body: str


class ChangelogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_or_phase_label: str
    title: str
    body: str
    published_at: datetime


class RoadmapSuggestionCreate(BaseModel):
    title: str
    body: str


class RoadmapSuggestionOut(BaseModel):
    id: str
    author_user_id: str
    title: str
    body: str
    created_at: datetime
    vote_count: int
    voted_by_me: bool


class TeamTaskCreate(BaseModel):
    title: str
    description: str | None = None
    project_uuid: str | None = None
    assigned_discipline: str | None = None
    source_type: str = "manual"
    source_ref: str | None = None


class TeamTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: Literal["open", "in_progress", "done"] | None = None
    assigned_discipline: str | None = None


class TeamTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    project_uuid: str | None
    title: str
    description: str | None
    status: str
    assigned_discipline: str | None
    source_type: str
    source_ref: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class CommentCreate(BaseModel):
    subject_type: Literal["task", "known_issue", "build", "session_summary"]
    subject_id: str
    body: str = Field(max_length=4000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    subject_type: str
    subject_id: str
    author_user_id: str
    body: str
    created_at: datetime


class EventRoutingRuleCreate(BaseModel):
    event_kind: str
    discipline: str


class EventRoutingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    event_kind: str
    discipline: str
    created_at: datetime


class TriggerRuleCreate(BaseModel):
    event_kind: str
    min_severity: str
    action: str
    action_params_json: str = "{}"
    enabled: bool = True


class TriggerRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    event_kind: str
    min_severity: str
    action: str
    action_params_json: str
    enabled: bool
    created_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    event_kind: str
    enabled: bool = True
    # Digest options (Phase K, section 9 part 1). Defaults to "realtime" so
    # existing callers built before this field existed keep working.
    delivery: Literal["realtime", "hourly", "daily"] = "realtime"


class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    user_id: str
    event_kind: str
    enabled: bool
    delivery: str
    created_at: datetime


class NotificationCreate(BaseModel):
    recipient_user_id: str
    event_kind: str
    title: str = Field(max_length=300)
    body: str = Field(max_length=4000)
    subject_type: str | None = None
    subject_id: str | None = Field(default=None, max_length=100)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    recipient_user_id: str
    event_kind: str
    title: str
    body: str
    subject_type: str | None
    subject_id: str | None
    created_at: datetime
    read_at: datetime | None
