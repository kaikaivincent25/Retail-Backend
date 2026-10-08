from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_cashier
from app.core.database import get_db
from app.models.shop import Shop
from app.models.user import User
from app.schemas.shop import PaymentDestinationRead, ShopRead, ShopUpdate

router = APIRouter(prefix="/shop", tags=["Shop"])

PAYMENT_DESTINATION_FIELDS = {
    "mpesa_pochi_number",
    "mpesa_till_number",
    "mpesa_paybill_number",
    "mpesa_paybill_account_number",
}


@router.get("", response_model=ShopRead)
def get_shop(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return db.get(Shop, user.shop_id)


@router.get("/payment-destinations", response_model=list[PaymentDestinationRead])
def get_payment_destinations(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    shop = db.get(Shop, user.shop_id)
    destinations = []
    if shop.mpesa_pochi_number:
        destinations.append(
            PaymentDestinationRead(
                method="pochi", label="Pochi la Biashara", number=shop.mpesa_pochi_number
            )
        )
    if shop.mpesa_till_number:
        destinations.append(
            PaymentDestinationRead(
                method="till", label="Buy Goods Till", number=shop.mpesa_till_number
            )
        )
    if shop.mpesa_paybill_number and shop.mpesa_paybill_account_number:
        destinations.append(
            PaymentDestinationRead(
                method="paybill",
                label="PayBill",
                number=shop.mpesa_paybill_number,
                account_number=shop.mpesa_paybill_account_number,
            )
        )
    return destinations


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

    if "location" in payload.model_fields_set:
        shop.location = payload.location
    if payload.currency:
        shop.currency = payload.currency
    for field in PAYMENT_DESTINATION_FIELDS & payload.model_fields_set:
        setattr(shop, field, getattr(payload, field))

    if shop.mpesa_paybill_number and not shop.mpesa_paybill_account_number:
        raise HTTPException(
            status_code=422,
            detail="A PayBill account number is required when a PayBill number is configured",
        )

    db.commit()
    db.refresh(shop)
    return shop
