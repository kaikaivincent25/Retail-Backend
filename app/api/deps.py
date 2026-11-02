from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.models.platform import PlatformUser
from app.models.shop import Shop
from app.models.billing import Subscription
from app.services.billing import is_service_blocked

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
platform_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/platform/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    try:
        subject = payload.get("sub")
        if not isinstance(subject, (str, int)):
            raise ValueError
        user_id = int(subject)
    except (TypeError, ValueError):
        raise credentials_error

    user = db.scalar(
        select(User).join(Shop, Shop.id == User.shop_id).where(User.id == user_id, Shop.is_suspended.is_(False))
    )
    if user is None or not user.is_active or payload.get("scope", "shop") != "shop":
        raise credentials_error
    subscription = db.scalar(select(Subscription).where(Subscription.shop_id == user.shop_id))
    if subscription is not None and is_service_blocked(subscription):
        raise HTTPException(status_code=402, detail="Your subscription is inactive. Open Billing to restore service.")
    return user


def get_current_user_for_billing(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None or payload.get("scope", "shop") != "shop":
        raise credentials_error
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise credentials_error
    user = db.scalar(select(User).join(Shop, Shop.id == User.shop_id).where(User.id == user_id))
    if user is None or not user.is_active:
        raise credentials_error
    return user


def get_current_platform_user(
    token: str = Depends(platform_oauth2_scheme), db: Session = Depends(get_db)
) -> PlatformUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate platform credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None or payload.get("scope") != "platform" or payload.get("role") != "platform_owner":
        raise credentials_error
    try:
        platform_user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise credentials_error
    platform_user = db.get(PlatformUser, platform_user_id)
    if platform_user is None or not platform_user.is_active:
        raise credentials_error
    return platform_user


def require_roles(*allowed: UserRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return checker


require_admin = require_roles(UserRole.ADMIN)
require_manager = require_roles(UserRole.ADMIN, UserRole.MANAGER)
require_cashier = require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.CASHIER)


def require_platform_owner(
    user: PlatformUser = Depends(get_current_platform_user),
) -> PlatformUser:
    return user
