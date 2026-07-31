from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select

from app.deps import AdminUser, CurrentUser, DbSession
from app.models import User
from app.schemas.auth import (
    PasswordChange,
    Token,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.schemas.common import Page
from app.security import create_access_token, hash_password, verify_password
from app.services.crud import commit, get_or_404

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=Token, summary="Log in")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    user = db.scalar(select(User).where(User.username == form.username))
    if user is None or not verify_password(form.password, user.hashed_password):
        # Same message either way, so the response cannot be used to probe
        # which usernames exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled"
        )

    token, expires_in = create_access_token(user.username, user.role)
    return Token(access_token=token, expires_in=expires_in)


@router.get("/auth/me", response_model=UserRead, summary="Current user")
def read_me(user: CurrentUser) -> User:
    return user


@router.post("/auth/change-password", summary="Change your own password")
def change_password(payload: PasswordChange, user: CurrentUser, db: DbSession) -> dict:
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is wrong"
        )
    user.hashed_password = hash_password(payload.new_password)
    commit(db)
    return {"detail": "Password updated"}


# --------------------------------------------------------------------------
# User administration
# --------------------------------------------------------------------------

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=Page[UserRead], summary="List users")
def list_users(db: DbSession, _admin: AdminUser, limit: int = 200, offset: int = 0):
    total = db.scalar(select(func.count()).select_from(User)) or 0
    rows = db.scalars(select(User).order_by(User.username).limit(limit).offset(offset)).all()
    return Page(
        items=[UserRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@users_router.post(
    "", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Create a user"
)
def create_user(payload: UserCreate, db: DbSession, _admin: AdminUser) -> User:
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already taken",
        )
    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role.value,
        is_active=payload.is_active,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    commit(db)
    db.refresh(user)
    return user


@users_router.patch("/{user_id}", response_model=UserRead, summary="Update a user")
def update_user(
    user_id: int, payload: UserUpdate, db: DbSession, admin: AdminUser
) -> User:
    user = get_or_404(db, User, user_id, "User")
    data = payload.model_dump(exclude_unset=True)

    if user.id == admin.id:
        if data.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot disable your own account",
            )
        if "role" in data and data["role"] != user.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot change your own role",
            )

    password = data.pop("password", None)
    role = data.pop("role", None)
    for key, value in data.items():
        setattr(user, key, value)
    if role is not None:
        user.role = role.value if hasattr(role, "value") else role
    if password:
        user.hashed_password = hash_password(password)

    commit(db)
    db.refresh(user)
    return user


@users_router.delete(
    "/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user"
)
def delete_user(user_id: int, db: DbSession, admin: AdminUser) -> None:
    user = get_or_404(db, User, user_id, "User")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    remaining_admins = db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.id != user_id)
    )
    if user.role == "admin" and not remaining_admins:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is the last administrator; promote someone else first",
        )
    db.delete(user)
    commit(db)
