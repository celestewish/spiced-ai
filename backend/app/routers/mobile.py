"""Companion Mobile View (Phase L, section 9 part 2, Stretch tier).

Per spec: "a separate lightweight mobile companion... mobile web or
lightweight app... read-only... no ability to trigger destructive actions."
Building and hosting a real separate mobile app/deployment is out of scope
for this session (no app-store/hosting account provisioning available
here). This is the honestly-scoped alternative: a single, responsive,
**read-only** HTML page served directly by this existing FastAPI backend --
no new frontend framework, no build step, inline ``<style>`` only.

Every route in this router is a plain ``GET`` -- there is deliberately no
form, no POST/PUT/PATCH/DELETE anywhere here, and no link that could trigger
one, matching the spec's explicit "no destructive actions" constraint. This
is verified by a test that inspects ``router.routes`` directly (see
``tests/test_mobile.py``), not just asserted in this docstring.

Scope-down on *what's shown*, documented rather than silently narrowed: the
spec's own example content is "build health" and a "feedback-themes
summary," but neither build reports nor feedback batches exist in this
backend's database at all -- both are local-only SQLite tables on the
desktop app (see ``storage.database.SCHEMA``'s ``build_reports``/
``feedback_batches`` tables), never synced to the team backend. What
genuinely *is* available server-side for a team-linked project is used
instead, and is a reasonable "build/game health" proxy in its own right:
- Recent notifications (Phase K) for the signed-in member on this team --
  this includes ``build_failed`` events, which the desktop client already
  posts here (see ``core.team_service.TeamService._notify_event``).
- Player crash reports (Phase G) for the team's linked project(s) -- a
  direct game-health signal, and one that (unlike build reports) is
  genuinely stored server-side.
- Team task counts (Phase J) -- a lightweight "what's still open" summary.

Auth: same Supabase bearer-token validation as the rest of this backend
(``app.auth.get_current_user``), via ``get_current_user_for_html`` -- see
that function's own docstring for why this endpoint additionally accepts
the token as a ``?token=`` query-string fallback (a plain HTML page a phone
browser navigates to can't set a custom ``Authorization`` header the way an
API client can).
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user_for_html
from app.db import get_db
from app.models import Notification, PlayerCrashReport, TeamProject, TeamTask, User
from app.routers.teams import _require_membership

router = APIRouter(prefix="/mobile", tags=["mobile"])

_NOTIFICATION_LIMIT = 20
_CRASH_LIMIT = 15
_OPEN_TASK_LIMIT = 15

_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 16px;
    max-width: 640px;
    margin-inline: auto;
    line-height: 1.4;
    color: #3A2C1F;
    background: #FBF3E4;
  }
  h1 { font-size: 1.3rem; margin-bottom: 0; }
  h2 {
    font-size: 1rem; text-transform: uppercase; letter-spacing: 0.05em;
    color: #6E5A48; margin-top: 1.75rem;
  }
  .muted { color: #6E5A48; font-size: 0.9rem; }
  .card {
    background: #FFFDF8; border: 1px solid #E7D7BE; border-radius: 12px;
    padding: 12px 14px; margin-bottom: 10px;
  }
  .badge {
    display: inline-block; border-radius: 8px; padding: 2px 8px;
    font-size: 0.75rem; font-weight: 600;
  }
  .badge.unread { background: #F6D9AF; color: #3A2C1F; }
  .badge.read { background: transparent; color: #6E5A48; }
  .empty { color: #6E5A48; font-style: italic; }
  .readonly-note { margin-top: 2rem; font-size: 0.8rem; color: #6E5A48; }
"""


def _page(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>{_PAGE_STYLE}</style>
</head>
<body>
{body_html}
<p class="readonly-note">Read-only view. Use the Spiced desktop app to take any action.</p>
</body>
</html>"""


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def mobile_team_view(
    team_id: str,
    project_uuid: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_for_html),
) -> HTMLResponse:
    """Read-only companion page for one team: recent notifications, player
    crash reports, and an open-task count -- see the module docstring for
    why these three, not "build health"/"feedback themes" verbatim.

    ``project_uuid``, if given, narrows crash reports and tasks to one
    linked project; omitted, it shows every linked project's data for the
    team. Requires the signed-in user to be a member of ``team_id`` (same
    gate as every other team-scoped read in this backend).
    """
    team = _require_membership(db, team_id, user)

    linked_projects = db.query(TeamProject).filter(TeamProject.team_id == team_id).all()
    project_uuids = (
        [project_uuid] if project_uuid else [p.project_uuid for p in linked_projects]
    )

    notifications = (
        db.query(Notification)
        .filter(Notification.team_id == team_id, Notification.recipient_user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(_NOTIFICATION_LIMIT)
        .all()
    )

    crash_reports = []
    if project_uuids:
        crash_reports = (
            db.query(PlayerCrashReport)
            .filter(PlayerCrashReport.project_uuid.in_(project_uuids))
            .order_by(PlayerCrashReport.reported_at.desc())
            .limit(_CRASH_LIMIT)
            .all()
        )

    tasks_query = db.query(TeamTask).filter(TeamTask.team_id == team_id)
    if project_uuid:
        tasks_query = tasks_query.filter(TeamTask.project_uuid == project_uuid)
    open_tasks = [t for t in tasks_query.all() if t.status != "done"]
    open_tasks.sort(key=lambda t: t.updated_at, reverse=True)

    body = f"<h1>{escape(team.name)}</h1>"
    body += (
        '<p class="muted">Companion view — read-only. Signed in as '
        f"{escape(user.email)}</p>"
    )

    body += "<h2>Notifications</h2>"
    if notifications:
        for note in notifications:
            badge_class, badge_text = ("read", "Read") if note.read_at else ("unread", "New")
            body += (
                '<div class="card">'
                f'<span class="badge {badge_class}">{badge_text}</span><br>'
                f"<strong>{escape(note.title)}</strong><br>"
                f"<span>{escape(note.body)}</span><br>"
                f'<span class="muted">{escape(str(note.created_at))}</span>'
                "</div>"
            )
    else:
        body += '<p class="empty">No notifications yet.</p>'

    body += "<h2>Player crash reports</h2>"
    if crash_reports:
        for report in crash_reports:
            body += (
                '<div class="card">'
                f"<strong>{escape(report.error_type)}</strong><br>"
                f"<span>{escape(report.message)}</span><br>"
                f'<span class="muted">'
                f"{escape(report.app_version or 'unknown version')} · "
                f"{escape(str(report.reported_at))}</span>"
                "</div>"
            )
    else:
        body += '<p class="empty">No player crash reports.</p>'

    body += "<h2>Open tasks</h2>"
    if open_tasks:
        body += f'<p class="muted">{len(open_tasks)} open task(s).</p>'
        for task in open_tasks[:_OPEN_TASK_LIMIT]:
            discipline = (
                f" · {escape(task.assigned_discipline)}" if task.assigned_discipline else ""
            )
            body += (
                '<div class="card">'
                f"<strong>{escape(task.title)}</strong><br>"
                f'<span class="muted">{escape(task.status)}{discipline}</span>'
                "</div>"
            )
    else:
        body += '<p class="empty">No open tasks.</p>'

    return HTMLResponse(content=_page(f"Spiced — {team.name}", body))
