from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.variant import Variant
from app.models.variant_price_history import VariantPriceHistory


def record_variant_price_change(
    db: Session,
    variant: Variant,
    user_id: int,
    old_price: Decimal | None,
) -> None:
    db.add(
        VariantPriceHistory(
            variant_id=variant.id,
            old_price=old_price,
            new_price=variant.selling_price,
            changed_by_user_id=user_id,
        )
    )
