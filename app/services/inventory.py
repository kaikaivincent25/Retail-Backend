from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stock_lot import StockLot, StockLotAllocation
from app.models.stock_movement import MovementType, StockMovement
from app.models.variant import Variant


@dataclass
class StockChangeResult:
    movement: StockMovement
    total_cost: Decimal


def apply_stock_change(
    db: Session,
    variant: Variant,
    delta: int,
    movement_type: MovementType,
    user_id: int,
    reason: str | None = None,
    unit_cost_at_time: Decimal | None = None,
    sale_item_id: int | None = None,
) -> StockChangeResult:
    """Change aggregate stock and allocate outgoing stock FIFO-style."""
    previous = variant.quantity
    new = previous + delta

    if new < 0:
        raise ValueError(
            f"Insufficient stock for '{variant.name}': "
            f"have {previous}, tried to remove {abs(delta)}"
        )

    movement = StockMovement(
        variant_id=variant.id,
        movement_type=movement_type,
        quantity=delta,
        previous_quantity=previous,
        new_quantity=new,
        reason=reason,
        user_id=user_id,
        unit_cost_at_time=unit_cost_at_time,
    )
    db.add(movement)
    db.flush()

    total_cost = Decimal("0.00")
    if delta > 0:
        lot_cost = unit_cost_at_time or (
            variant.cost_price if variant.cost_price_is_known else None
        )
        if lot_cost is None:
            raise ValueError("A unit cost is required before adding stock")
        db.add(StockLot(
            variant_id=variant.id,
            received_quantity=delta,
            remaining_quantity=delta,
            unit_cost=lot_cost,
        ))
        total_cost = lot_cost * delta
    elif delta < 0:
        remaining = abs(delta)
        lots = db.scalars(
            select(StockLot)
            .where(
                StockLot.variant_id == variant.id,
                StockLot.remaining_quantity > 0,
            )
            .order_by(StockLot.created_at, StockLot.id)
            .with_for_update()
        ).all()
        available = sum(lot.remaining_quantity for lot in lots)
        if available < remaining:
            raise ValueError(
                f"Stock lots do not cover '{variant.name}': "
                f"have {available}, tried to remove {remaining}"
            )
        for lot in lots:
            if remaining == 0:
                break
            allocated = min(lot.remaining_quantity, remaining)
            lot.remaining_quantity -= allocated
            total_cost += lot.unit_cost * allocated
            db.add(StockLotAllocation(
                lot_id=lot.id,
                stock_movement_id=movement.id,
                sale_item_id=sale_item_id,
                quantity=allocated,
                unit_cost=lot.unit_cost,
            ))
            remaining -= allocated
        movement.unit_cost_at_time = (
            total_cost / abs(delta)
        ).quantize(Decimal("0.01"))

    variant.quantity = new
    return StockChangeResult(movement=movement, total_cost=total_cost)


def restore_reserved_stock(
    db: Session,
    variant: Variant,
    quantity: int,
    user_id: int,
    reason: str,
    sale_item_id: int,
) -> StockMovement:
    """Return a pending reservation to the exact lots it came from."""
    allocations = db.scalars(
        select(StockLotAllocation)
        .where(StockLotAllocation.sale_item_id == sale_item_id)
        .order_by(StockLotAllocation.id.desc())
        .with_for_update()
    ).all()
    restored = sum(item.quantity for item in allocations)
    if restored != quantity:
        raise ValueError("Reserved stock allocation is incomplete")

    previous = variant.quantity
    movement = StockMovement(
        variant_id=variant.id,
        movement_type=MovementType.ADJUSTMENT,
        quantity=quantity,
        previous_quantity=previous,
        new_quantity=previous + quantity,
        reason=reason,
        user_id=user_id,
    )
    db.add(movement)
    db.flush()
    for allocation in allocations:
        lot = db.scalar(
            select(StockLot).where(StockLot.id == allocation.lot_id).with_for_update()
        )
        if lot is None:
            raise ValueError("Reserved stock lot no longer exists")
        lot.remaining_quantity += allocation.quantity
        allocation.sale_item_id = None
    variant.quantity += quantity
    return movement
