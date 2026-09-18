from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app import auth
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, bool]:
    await auth.login(request, response, payload.password)
    return {"authenticated": True}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    auth.clear_session(response)
    return {"authenticated": False}


@router.get("/me")
async def me(request: Request) -> dict[str, bool]:
    return {
        "authenticated": auth.is_authenticated(request),
        "configured": bool(get_settings().password_hash),
    }
