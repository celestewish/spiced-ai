"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import player_crashes, roadmap, sessions, teams, telemetry

app = FastAPI(title="Spiced Backend", version="0.0.1")

# The desktop client is not a browser page with a fixed origin, so CORS is
# permissive for local development. Tighten this to the deployed client's
# origin(s) before shipping a public instance.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(sessions.router)
app.include_router(telemetry.router)
app.include_router(roadmap.router)
app.include_router(player_crashes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
