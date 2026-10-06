from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.activity_log import ActivityAction
from app.models.shop import Shop
from app.models.user import User, UserRole
from app.schemas.auth import Token
from app.schemas.shop import ShopSignup
from app.schemas.user import PasswordChange, ProfileUpdate, UserRead
from app.services.audit import log_activity

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=Token, status_code=201)
def signup(payload: ShopSignup, db: Session = Depends(get_db)):
    if db.scalar(select(Shop).where(Shop.name == payload.shop_name)):
        raise HTTPException(
            status_code=409,
            detail=f"A shop named '{payload.shop_name}' already exists",
        )

    if db.scalar(select(User).where(User.username == payload.admin_username)):
        raise HTTPException(
            status_code=409,
            detail=f"Username '{payload.admin_username}' is already taken",
        )

    shop = Shop(name=payload.shop_name, location=payload.shop_location, currency="KES")
    db.add(shop)
    db.flush()

    admin = User(
        shop_id=shop.id,
        full_name=payload.admin_full_name,
        username=payload.admin_username,
        password_hash=hash_password(payload.admin_password),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.flush()

    log_activity(
        db,
        user_id=admin.id,
        action=ActivityAction.LOGIN,
        description="Account created (new shop signup)",
    )
    db.commit()

    token = create_access_token(subject=str(admin.id), role=admin.role.value)
    return Token(access_token=token, role=admin.role.value)


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.scalar(select(User).where(User.username == form_data.username))

    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled"
        )

    token = create_access_token(subject=str(user.id), role=user.role.value)
    log_activity(db, user_id=user.id, action=ActivityAction.LOGIN)
    db.commit()
    return Token(access_token=token, role=user.role.value)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.username and payload.username != current_user.username:
        if db.scalar(select(User).where(User.username == payload.username)):
            raise HTTPException(
                status_code=409,
                detail=f"Username '{payload.username}' is already taken",
            )
        current_user.username = payload.username

    if payload.full_name:
        current_user.full_name = payload.full_name

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=422, detail="Current password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
