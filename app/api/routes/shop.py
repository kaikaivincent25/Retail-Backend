from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_cashier
from app.core.database import get_db
from app.models.shop import Shop
from app.models.activity_log import ActivityLog
from app.models.bulk_preset import BulkPreset
from app.models.cash_deposit import CashDeposit
from app.models.cash_session import CashSession
from app.models.expense import Expense
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.models.variant import Variant
from app.core.security import verify_password
from app.schemas.shop import (
    PaymentDestinationRead,
    ShopRead,
    ShopReceiptRead,
    ShopDeleteRequest,
    ShopUpdate,
)

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


@router.get("/receipt-profile", response_model=ShopReceiptRead)
def get_receipt_profile(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
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
    if "business_type" in payload.model_fields_set and payload.business_type:
        shop.business_type = payload.business_type
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


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_shop(
    payload: ShopDeleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    # Lock the tenant row while deleting to prevent two concurrent delete requests.
    shop = db.scalar(select(Shop).where(Shop.id == user.shop_id).with_for_update())
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if payload.shop_name != shop.name:
        raise HTTPException(status_code=422, detail="Shop name confirmation does not match")

    shop_users = select(User.id).where(User.shop_id == shop.id)
    shop_sales = select(Sale.id).where(Sale.shop_id == shop.id)
    shop_products = select(Product.id).where(Product.shop_id == shop.id)
    shop_variants = select(Variant.id).where(Variant.product_id.in_(shop_products))

    try:
        # Remove dependent records first. All predicates are scoped to this tenant.
        db.execute(delete(SaleItem).where(SaleItem.sale_id.in_(shop_sales)))
        db.execute(delete(Sale).where(Sale.shop_id == shop.id))
        db.execute(delete(CashDeposit).where(CashDeposit.shop_id == shop.id))
        db.execute(delete(Expense).where(Expense.user_id.in_(shop_users)))
        db.execute(delete(StockMovement).where(StockMovement.variant_id.in_(shop_variants)))
        db.execute(delete(BulkPreset).where(BulkPreset.variant_id.in_(shop_variants)))
        db.execute(delete(Variant).where(Variant.product_id.in_(shop_products)))
        db.execute(delete(Product).where(Product.shop_id == shop.id))
        db.execute(delete(CashSession).where(CashSession.shop_id == shop.id))
        db.execute(delete(ActivityLog).where(ActivityLog.user_id.in_(shop_users)))
        db.execute(delete(User).where(User.shop_id == shop.id))
        db.delete(shop)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Shop data changed during deletion. No data was removed; please try again.",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
