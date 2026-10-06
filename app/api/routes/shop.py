from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.shop import Shop
from app.models.user import User
from app.schemas.shop import ShopRead, ShopUpdate

router = APIRouter(prefix="/shop", tags=["Shop"])


@router.get("", response_model=ShopRead)
def get_shop(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.get(Shop, user.shop_id)


@router.patch("", response_model=ShopRead)
def update_shop(
    payload: ShopUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    shop = db.get(Shop, user.shop_id)

    if payload.name and payload.name != shop.name:
        if db.scalar(select(Shop).where(Shop.name == payload.name, Shop.id != shop.id)):
            raise HTTPException(
                status_code=409,
                detail=f"A shop named '{payload.name}' already exists",
            )
        shop.name = payload.name

    if payload.location is not None:
        shop.location = payload.location
    if payload.currency:
        shop.currency = payload.currency

    db.commit()
    db.refresh(shop)
    return shop
