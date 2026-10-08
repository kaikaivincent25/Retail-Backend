from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sale import PaymentMethod, Sale, SaleItem, SaleStatus
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
        if payment_method != PaymentMethod.CASH:
            raise SaleError("M-Pesa payments must use the STK Push checkout flow")
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


def create_pending_mpesa_sale(
    db: Session,
    shop_id: int,
    cashier_id: int,
    items: list[dict],
    phone_number: str,
    session_id: int,
) -> Sale:
    """Create a pending order and reserve its stock until Daraja reports the result."""
    try:
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
                .with_for_update()
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

        if subtotal <= 0:
            raise SaleError("M-Pesa payment amount must be greater than zero")
        if subtotal != subtotal.to_integral_value():
            raise SaleError(
                "M-Pesa STK Push supports whole KSh amounts only. "
                "Adjust the cart so its total is a whole shilling."
            )

        sale = Sale(
            shop_id=shop_id,
            cashier_id=cashier_id,
            session_id=session_id,
            subtotal=subtotal,
            total=subtotal,
            amount_received=Decimal("0.00"),
            change=Decimal("0.00"),
            payment_method=PaymentMethod.MPESA,
            status=SaleStatus.PENDING,
            mpesa_phone_number=phone_number,
        )
        db.add(sale)
        db.flush()

        for variant, quantity in resolved:
            sale.items.append(
                SaleItem(
                    variant_id=variant.id,
                    variant_name=variant.name,
                    quantity=quantity,
                    unit_price=variant.selling_price,
                    line_total=variant.selling_price * quantity,
                )
            )
            apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.ADJUSTMENT,
                user_id=cashier_id,
                reason=f"Reserved for pending M-Pesa sale #{sale.id}",
            )

        db.commit()
        db.refresh(sale)
        return sale
    except Exception:
        db.rollback()
        raise


def create_pending_manual_sale(
    db: Session,
    shop_id: int,
    cashier_id: int,
    items: list[dict],
    payment_method: PaymentMethod,
    destination_number: str,
    account_number: str | None,
    session_id: int,
) -> Sale:
    try:
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
                .with_for_update()
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

        if subtotal <= 0:
            raise SaleError("M-Pesa payment amount must be greater than zero")

        sale = Sale(
            shop_id=shop_id,
            cashier_id=cashier_id,
            session_id=session_id,
            subtotal=subtotal,
            total=subtotal,
            amount_received=Decimal("0.00"),
            change=Decimal("0.00"),
            payment_method=payment_method,
            status=SaleStatus.PENDING,
            payment_destination_number=destination_number,
            payment_account_number=account_number,
        )
        db.add(sale)
        db.flush()

        for variant, quantity in resolved:
            sale.items.append(
                SaleItem(
                    variant_id=variant.id,
                    variant_name=variant.name,
                    quantity=quantity,
                    unit_price=variant.selling_price,
                    line_total=variant.selling_price * quantity,
                )
            )
            apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.ADJUSTMENT,
                user_id=cashier_id,
                reason=f"Reserved for pending manual M-Pesa sale #{sale.id}",
            )

        db.commit()
        db.refresh(sale)
        return sale
    except Exception:
        db.rollback()
        raise


def confirm_manual_payment(
    db: Session, sale: Sale, receipt_number: str, confirmed_by_user_id: int
) -> Sale:
    if sale.status != SaleStatus.PENDING or sale.payment_method not in {
        PaymentMethod.POCHI,
        PaymentMethod.TILL,
        PaymentMethod.PAYBILL,
    }:
        raise SaleError("This sale is not awaiting a manual M-Pesa payment")

    sale.status = SaleStatus.COMPLETED
    sale.amount_received = sale.total
    sale.change = Decimal("0.00")
    sale.mpesa_receipt_number = receipt_number
    log_activity(
        db,
        user_id=confirmed_by_user_id,
        action=ActivityAction.SALE_COMPLETED,
        entity_type="sale",
        entity_id=sale.id,
        description=f"Manual M-Pesa payment confirmed for sale #{sale.id}: {receipt_number}",
    )
    db.commit()
    db.refresh(sale)
    return sale


def release_pending_sale(db: Session, sale_id: int) -> Sale | None:
    sale = db.scalar(select(Sale).where(Sale.id == sale_id).with_for_update())
    if sale is None or sale.status != SaleStatus.PENDING:
        return sale

    is_manual = sale.payment_method in {
        PaymentMethod.POCHI,
        PaymentMethod.TILL,
        PaymentMethod.PAYBILL,
    }
    for item in sale.items:
        variant = db.scalar(
            select(Variant).where(Variant.id == item.variant_id).with_for_update()
        )
        if variant is None:
            raise SaleError(f"Reserved variant {item.variant_id} no longer exists")
        apply_stock_change(
            db,
            variant,
            delta=item.quantity,
            movement_type=MovementType.ADJUSTMENT,
            user_id=sale.cashier_id,
            reason=(
                f"Released cancelled manual M-Pesa sale #{sale.id}"
                if is_manual
                else f"Released failed M-Pesa sale #{sale.id}"
            ),
        )

    sale.status = SaleStatus.FAILED
    db.commit()
    db.refresh(sale)
    return sale