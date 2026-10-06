from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' already exists")

    new_user = User(
        shop_id=user.shop_id,
        full_name=payload.full_name,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    query = select(User).where(User.shop_id == user.shop_id).order_by(User.full_name)
    return db.scalars(query).all()


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.scalar(select(User).where(User.id == user_id, User.shop_id == user.shop_id))
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.id == user.id and payload.is_active is False:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    if target.id == user.id and payload.role is not None and payload.role.value != "admin":
        raise HTTPException(status_code=422, detail="You cannot change your own role")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)

    db.commit()
    db.refresh(target)
    return target