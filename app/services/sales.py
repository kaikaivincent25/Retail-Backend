from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sale import PaymentMethod, Sale, SaleItem
from app.models.stock_movement import MovementType
from app.models.variant import Variant
from app.services.inventory import apply_stock_change
from app.models.activity_log import ActivityAction
from app.services.audit import log_activity


class SaleError(Exception):
    """Raised for any business-rule failure while completing a sale."""


def complete_sale(
    db: Session,
    shop_id: int,
    cashier_id: int,
    items: list[dict],          # [{"variant_id": int, "quantity": int}, ...]
    amount_received: Decimal,
    payment_method: PaymentMethod = PaymentMethod.CASH,
    session_id: int | None = None,
) -> Sale:
    try:
        # 1. Validate every variant up front, and check stock, before writing anything
        resolved: list[tuple[Variant, int]] = []
        subtotal = Decimal("0.00")

        for entry in items:
            variant = db.scalar(
                select(Variant)
                .join(Product)
                .where(
                    Variant.id == entry["variant_id"],
                    Product.shop_id == shop_id,
                    Variant.is_active.is_(True),
                )
            )
            if variant is None:
                raise SaleError(f"Variant {entry['variant_id']} not found or inactive")

            quantity = entry["quantity"]
            if variant.quantity < quantity:
                raise SaleError(
                    f"Insufficient stock for '{variant.name}': "
                    f"have {variant.quantity}, requested {quantity}"
                )

            subtotal += variant.selling_price * quantity
            resolved.append((variant, quantity))

        total = subtotal  # no tax/discount logic yet — kept simple for the MVP
        if amount_received < total:
            raise SaleError(
                f"Amount received ({amount_received}) is less than the total ({total})"
            )
        change = amount_received - total

        # 2. Create the sale header
        sale = Sale(
            shop_id=shop_id,
            cashier_id=cashier_id,
            session_id=session_id,
            subtotal=subtotal,
            total=total,
            amount_received=amount_received,
            change=change,
            payment_method=payment_method,
        )
        db.add(sale)
        db.flush()  # assigns sale.id without committing, so sale_items can reference it

        # 3. Create sale items, decrease inventory, and log stock movements
        for variant, quantity in resolved:
            line_total = variant.selling_price * quantity
            sale.items.append(SaleItem(
                variant_id=variant.id,
                variant_name=variant.name,
                quantity=quantity,
                unit_price=variant.selling_price,
                line_total=line_total,
            ))

            apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.SALE,
                user_id=cashier_id,
                reason=f"Sale #{sale.id}",
            )
        log_activity(
            db, user_id=cashier_id, action=ActivityAction.SALE_COMPLETED,
            entity_type="sale", entity_id=sale.id,
            description=f"Sale #{sale.id} total {sale.total}",
        )
        # 4. Everything succeeded — commit as one unit
        db.commit()
        db.refresh(sale)
        return sale

    except Exception:
        db.rollback()
        raise