from fastapi import APIRouter, Depends, HTTPException, Query
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.product import Product
from app.models.stock_movement import MovementType, StockMovement
from app.models.sale import SaleItem
from app.models.user import User
from app.models.variant import Variant
from app.schemas.inventory import (
    StaffConsumptionCreate,
    StockAdjustment,
    StockMovementRead,
    VariantCostRead,
    VariantStockRead,
)
from app.services.inventory import apply_stock_change
from app.models.activity_log import ActivityAction
from app.services.audit import log_activity

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def get_owned_variant(db: Session, variant_id: int, shop_id: int) -> Variant:
    variant = db.scalar(
        select(Variant)
        .join(Product)
        .where(Variant.id == variant_id, Product.shop_id == shop_id)
    )
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return variant


@router.get("", response_model=list[VariantStockRead])
def list_inventory(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = (
        select(Variant)
        .join(Product)
        .where(Product.shop_id == user.shop_id, Variant.is_active.is_(True))
        .order_by(Variant.name)
    )
    return db.scalars(query).all()


@router.get("/low-stock", response_model=list[VariantStockRead])
def low_stock(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = (
        select(Variant)
        .join(Product)
        .where(
            Product.shop_id == user.shop_id,
            Variant.is_active.is_(True),
            Variant.quantity <= Variant.reorder_level,
        )
        .order_by(Variant.quantity)
    )
    return db.scalars(query).all()


@router.get("/costs", response_model=list[VariantCostRead])
def inventory_costs(
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    query = (
        select(
            Variant.id,
            Variant.cost_price,
            Variant.cost_price_is_known,
        )
        .join(Product)
        .where(Product.shop_id == user.shop_id, Variant.is_active.is_(True))
        .order_by(Variant.id)
    )
    return [
        VariantCostRead(**row._mapping)
        for row in db.execute(query).all()
    ]


@router.post("/{variant_id}/adjust", response_model=VariantStockRead)
def adjust_stock(
    variant_id: int,
    payload: StockAdjustment,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    if payload.movement_type == MovementType.SALE:
        raise HTTPException(
            status_code=422,
            detail="SALE movements can only be created by completing a sale",
        )
    if payload.movement_type == MovementType.STAFF_CONSUMPTION:
        raise HTTPException(
            status_code=422,
            detail="STAFF_CONSUMPTION movements can only be created through staff consumption",
        )

    variant = db.scalar(
        select(Variant).join(Product).where(
            Variant.id == variant_id, Product.shop_id == user.shop_id
        ).with_for_update()
    )
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")

    if payload.movement_type == MovementType.PURCHASE:
        if payload.delta <= 0:
            raise HTTPException(status_code=422, detail="A purchase must add stock")
        if payload.unit_cost is None:
            if not variant.cost_price_is_known:
                raise HTTPException(
                    status_code=422,
                    detail="Unit purchase cost is required when receiving stock (no recorded cost yet)",
                )
            payload.unit_cost = variant.cost_price
        if variant.quantity and not variant.cost_price_is_known:
            raise HTTPException(
                status_code=422,
                detail="Record the cost of existing stock before receiving another purchase",
            )

        previous_value = variant.cost_price * variant.quantity
        purchase_value = payload.unit_cost * payload.delta
        variant.cost_price = (
            (previous_value + purchase_value) / (variant.quantity + payload.delta)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        variant.cost_price_is_known = True
    elif payload.movement_type == MovementType.DAMAGE and payload.delta >= 0:
        raise HTTPException(status_code=422, detail="Damage must remove stock")

    movement_unit_cost = (
        payload.unit_cost
        if payload.movement_type == MovementType.PURCHASE
        else (variant.cost_price if variant.cost_price_is_known and payload.delta < 0 else None)
    )

    try:
        apply_stock_change(
            db,
            variant,
            delta=payload.delta,
            movement_type=payload.movement_type,
            user_id=user.id,
            reason=payload.reason,
            unit_cost_at_time=movement_unit_cost,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    
    log_activity(
        db, user_id=user.id, action=ActivityAction.INVENTORY_ADJUSTED,
        entity_type="variant", entity_id=variant.id,
        description=(
            f"{payload.movement_type.value}: {payload.delta:+d}"
            f"{f' at {movement_unit_cost} each' if movement_unit_cost is not None else ''}"
            f" ({payload.reason or 'no reason given'})"
        )[:255],
    )

    db.commit()
    db.refresh(variant)
    return variant


@router.post("/{variant_id}/staff-consumption", response_model=StockMovementRead, status_code=201)
def record_staff_consumption(
    variant_id: int,
    payload: StaffConsumptionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    variant = db.scalar(
        select(Variant)
        .join(Product)
        .where(Variant.id == variant_id, Product.shop_id == user.shop_id)
        .with_for_update()
    )
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")

    reason = (
        payload.reason.strip()
        if payload.reason and payload.reason.strip()
        else "Staff consumption"
    )
    try:
        movement = apply_stock_change(
            db,
            variant,
            delta=-payload.quantity,
            movement_type=MovementType.STAFF_CONSUMPTION,
            user_id=user.id,
            reason=reason,
            unit_cost_at_time=variant.cost_price,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))

    db.flush()
    log_activity(
        db,
        user_id=user.id,
        action=ActivityAction.STAFF_CONSUMPTION_RECORDED,
        entity_type="stock_movement",
        entity_id=movement.id,
        description=f"{payload.quantity} of {variant.name}: {reason}"[:255],
    )
    db.commit()
    db.refresh(movement)
    return movement


@router.get("/{variant_id}/movements", response_model=list[StockMovementRead])
def variant_movements(
    variant_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    get_owned_variant(db, variant_id, user.shop_id)  # 404s if not yours

    query = (
        select(StockMovement)
        .where(StockMovement.variant_id == variant_id)
        .order_by(StockMovement.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return db.scalars(query).all()
