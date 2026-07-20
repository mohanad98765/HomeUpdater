"""Auth endpoints — the app-level password login gate (see services/auth.py)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import auth

router = APIRouter()


class PasswordBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


class ChangeBody(BaseModel):
    current: str = Field(..., max_length=256)
    new: str = Field(..., min_length=1, max_length=256)


@router.get("/status")
async def status() -> dict:
    """Whether a password has been set yet (drives first-run vs. login UI)."""
    return {"password_set": auth.is_password_set()}


@router.get("/check")
async def check() -> dict:
    """Validate the current login session. Gated (NOT exempt), so it only
    returns 200 when the X-HomeUpdater-Auth session is valid; otherwise the
    middleware returns 401. The UI uses this to confirm a stored token up front
    (avoiding a flash of the app on a stale token)."""
    return {"ok": True}


@router.post("/setup")
async def setup(body: PasswordBody) -> dict:
    """First-run: create the password. Refused once one already exists."""
    if auth.is_password_set():
        raise HTTPException(status_code=409, detail="كلمة المرور مُعيّنة بالفعل.")
    try:
        auth.set_password(body.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"token": auth.create_session()}


@router.post("/login")
async def login(body: PasswordBody) -> dict:
    """Verify the password and issue a session token."""
    if not auth.is_password_set():
        raise HTTPException(status_code=409, detail="لم تُعيَّن كلمة مرور بعد.")
    if not auth.verify_password(body.password):
        raise HTTPException(status_code=401, detail="كلمة المرور غير صحيحة.")
    return {"token": auth.create_session()}


@router.post("/change")
async def change(body: ChangeBody, request: Request) -> dict:
    """Change the password (requires the current one). Invalidates other sessions."""
    try:
        auth.change_password(body.current, body.new)
    except auth.AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.revoke_all()  # force re-login everywhere after a password change
    return {"token": auth.create_session()}


@router.post("/logout")
async def logout(request: Request) -> dict:
    auth.revoke_session(request.headers.get("x-homeupdater-auth", ""))
    return {"ok": True}
