from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.stock_movement import MovementType, StockMovement
from app.models.variant import Variant


def apply_stock_change(
    db: Session,
    variant: Variant,
    delta: int,
    movement_type: MovementType,
    user_id: int,
    reason: str | None = None,
    unit_cost_at_time: Decimal | None = None,
) -> StockMovement:
    """
    The ONLY function allowed to change variant.quantity.
    delta is signed: positive adds stock, negative removes it.
    Does not commit — caller controls the transaction boundary.
    """
    previous = variant.quantity
    new = previous + delta

    if new < 0:
        raise ValueError(
            f"Insufficient stock for '{variant.name}': "
            f"have {previous}, tried to remove {abs(delta)}"
        )

    variant.quantity = new

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
    return movement