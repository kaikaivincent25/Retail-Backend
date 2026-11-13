from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.customer import Customer
from app.models.customer_payment import CustomerPayment
from app.models.product import Product
from app.models.sale import PaymentMethod, Sale, SaleItem, SaleStatus
from app.models.stock_movement import MovementType
from app.models.variant import Variant
from app.services.inventory import apply_stock_change, restore_reserved_stock
from app.models.activity_log import ActivityAction
from app.services.audit import log_activity
from app.services.accounting import post_completed_sale, post_customer_payment
from app.services.customer_payments import calculate_customer_outstanding


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
    client_id: UUID | None = None,
    customer_id: int | None = None,
    is_credit: bool = False,
    due_date: date | None = None,
    initial_payment: Decimal | None = None,
    initial_payment_method: PaymentMethod | None = None,
    allow_confirmed_mpesa: bool = False,
) -> Sale:
    try:
        if is_credit:
            if customer_id is None:
                raise SaleError("A customer must be selected for credit purchases")
            if due_date is None:
                raise SaleError("Every credit sale requires a due date")
            if due_date < date.today():
                raise SaleError("Credit due date cannot be in the past")
            customer = db.scalar(
                select(Customer)
                .where(Customer.id == customer_id, Customer.shop_id == shop_id)
                .with_for_update()
            )
            if customer is None:
                raise SaleError("Customer not found")
            if not customer.is_active:
                raise SaleError("Cannot make credit sales to an inactive customer")
            init_amt = initial_payment or Decimal("0.00")
            if init_amt < 0:
                raise SaleError("Initial payment cannot be negative")
            if init_amt > 0 and initial_payment_method is None:
                initial_payment_method = PaymentMethod.CASH
        elif payment_method != PaymentMethod.CASH and not (
            payment_method == PaymentMethod.MPESA and allow_confirmed_mpesa
        ):
            raise SaleError("M-Pesa payments must use the STK Push checkout flow")
        # Lock variants in a stable order so concurrent checkouts cannot oversell.
        variant_ids = {entry["variant_id"] for entry in items}
        variants = db.scalars(
            select(Variant)
            .join(Product)
            .where(
                Variant.id.in_(variant_ids),
                Product.shop_id == shop_id,
                Variant.is_active.is_(True),
            )
            .order_by(Variant.id)
            .with_for_update(of=Variant)
        ).all()
        variants_by_id = {variant.id: variant for variant in variants}

        # Validate every variant and the total requested quantity before writing.
        resolved: list[tuple[Variant, int]] = []
        subtotal = Decimal("0.00")
        requested_by_variant: dict[int, int] = {}
        for entry in items:
            variant_id = entry["variant_id"]
            quantity = entry["quantity"]
            if quantity <= 0:
                raise SaleError("Sale quantities must be greater than zero")
            requested_by_variant[variant_id] = (
                requested_by_variant.get(variant_id, 0) + quantity
            )

        for variant_id, quantity in requested_by_variant.items():
            variant = variants_by_id.get(variant_id)
            if variant is None:
                raise SaleError(f"Variant {variant_id} not found or inactive")
            if variant.quantity < quantity:
                raise SaleError(
                    f"Insufficient stock for '{variant.name}': "
                    f"have {variant.quantity}, requested {quantity}"
                )
            if not variant.cost_price_is_known:
                raise SaleError(
                    f"Cost is not recorded for '{variant.name}'. Receive stock with a purchase cost before selling it."
                )
            subtotal += variant.selling_price * quantity
            resolved.append((variant, quantity))

        total = subtotal  # no tax/discount logic yet — kept simple for the MVP
        if is_credit:
            if init_amt > total:
                raise SaleError(
                    f"Initial payment ({init_amt}) cannot exceed the total ({total})"
                )
            credit_amount = total - init_amt
            if customer.credit_limit is not None:
                outstanding, _ = calculate_customer_outstanding(db, shop_id, customer_id)
                if outstanding + credit_amount > customer.credit_limit:
                    raise SaleError(
                        f"Credit limit of {customer.credit_limit} exceeded. "
                        f"Current outstanding is {outstanding}, requested credit is {credit_amount}"
                    )
            amount_received = init_amt
            change = Decimal("0.00")
        elif amount_received < total:
            raise SaleError(
                f"Amount received ({amount_received}) is less than the total ({total})"
            )
        if not is_credit:
            change = amount_received - total

        # 2. Create the sale header
        sale = Sale(
            shop_id=shop_id,
            cashier_id=cashier_id,
            client_id=client_id,
            session_id=session_id,
            customer_id=customer_id,
            is_credit=is_credit,
            due_date=due_date,
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
            sale_item = SaleItem(
                variant_id=variant.id,
                variant_name=variant.name,
                quantity=quantity,
                unit_price=variant.selling_price,
                unit_cost_at_sale=variant.cost_price,
                cost_is_known_at_sale=variant.cost_price_is_known,
                line_total=line_total,
            )
            sale.items.append(sale_item)
            db.flush()

            result = apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.SALE,
                user_id=cashier_id,
                reason=f"Sale #{sale.id}",
                unit_cost_at_time=variant.cost_price,
                sale_item_id=sale_item.id,
            )
            sale_item.unit_cost_at_sale = result.total_cost / quantity
            sale_item.cost_is_known_at_sale = True
        initial_payment_record = None
        if is_credit and init_amt > 0:
            initial_payment_record = CustomerPayment(
                shop_id=shop_id,
                customer_id=customer_id,
                sale_id=sale.id,
                session_id=session_id if initial_payment_method == PaymentMethod.CASH else None,
                amount=init_amt,
                payment_method=initial_payment_method,
                reference="Down payment at checkout",
                recorded_by_user_id=cashier_id,
            )
            db.add(initial_payment_record)
            db.flush()

        sale_desc = (
            f"Credit sale #{sale.id} total {sale.total} for customer #{customer.id}"
            if is_credit
            else f"Sale #{sale.id} total {sale.total}"
        )
        log_activity(
            db, user_id=cashier_id, action=ActivityAction.SALE_COMPLETED,
            entity_type="sale", entity_id=sale.id,
            description=sale_desc,
        )
        post_completed_sale(db, sale)
        if initial_payment_record is not None:
            post_customer_payment(db, initial_payment_record)
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
            if not variant.cost_price_is_known:
                raise SaleError(
                    f"Cost is not recorded for '{variant.name}'. Receive stock with a purchase cost before selling it."
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
            sale_item = SaleItem(
                    variant_id=variant.id,
                    variant_name=variant.name,
                    quantity=quantity,
                    unit_price=variant.selling_price,
                    unit_cost_at_sale=variant.cost_price,
                    cost_is_known_at_sale=variant.cost_price_is_known,
                    line_total=variant.selling_price * quantity,
                )
            sale.items.append(sale_item)
            db.flush()
            result = apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.ADJUSTMENT,
                user_id=cashier_id,
                reason=f"Reserved for pending M-Pesa sale #{sale.id}",
                unit_cost_at_time=variant.cost_price,
                sale_item_id=sale_item.id,
            )
            sale_item.unit_cost_at_sale = result.total_cost / quantity
            sale_item.cost_is_known_at_sale = True

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
            if not variant.cost_price_is_known:
                raise SaleError(
                    f"Cost is not recorded for '{variant.name}'. Receive stock with a purchase cost before selling it."
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
            sale_item = SaleItem(
                    variant_id=variant.id,
                    variant_name=variant.name,
                    quantity=quantity,
                    unit_price=variant.selling_price,
                    unit_cost_at_sale=variant.cost_price,
                    cost_is_known_at_sale=variant.cost_price_is_known,
                    line_total=variant.selling_price * quantity,
                )
            sale.items.append(sale_item)
            db.flush()
            result = apply_stock_change(
                db,
                variant,
                delta=-quantity,
                movement_type=MovementType.ADJUSTMENT,
                user_id=cashier_id,
                reason=f"Reserved for pending manual M-Pesa sale #{sale.id}",
                unit_cost_at_time=variant.cost_price,
                sale_item_id=sale_item.id,
            )
            sale_item.unit_cost_at_sale = result.total_cost / quantity
            sale_item.cost_is_known_at_sale = True

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
    post_completed_sale(db, sale)
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


def release_pending_sale(
    db: Session,
    sale_id: int,
    *,
    released_by_user_id: int | None = None,
) -> Sale | None:
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
        restore_reserved_stock(
            db,
            variant,
            quantity=item.quantity,
            user_id=sale.cashier_id,
            reason=(
                f"Released cancelled manual M-Pesa sale #{sale.id}"
                if is_manual
                else f"Released failed M-Pesa sale #{sale.id}"
            ),
            sale_item_id=item.id,
        )

    sale.status = SaleStatus.FAILED
    log_activity(
        db,
        user_id=released_by_user_id or sale.cashier_id,
        action=ActivityAction.SALE_PAYMENT_FAILED,
        entity_type="sale",
        entity_id=sale.id,
        description=(
            f"Manual M-Pesa payment cancelled for sale #{sale.id}"
            if is_manual
            else f"M-Pesa payment failed for sale #{sale.id}"
        ),
    )
    db.commit()
    db.refresh(sale)
    return sale


def apply_stk_reconciliation(
    db: Session,
    sale_id: int,
    status: str,
    reconciled_by_user_id: int,
) -> Sale:
    try:
        sale = db.scalar(
            select(Sale)
            .where(Sale.id == sale_id)
            .options(selectinload(Sale.items))
            .with_for_update()
        )
        if sale is None:
            raise SaleError("Sale not found")
        if sale.payment_method != PaymentMethod.MPESA:
            raise SaleError("This sale is not an STK M-Pesa payment")
        if sale.status != SaleStatus.PENDING:
            return sale

        if status == "completed":
            sale.status = SaleStatus.COMPLETED
            sale.amount_received = sale.total
            sale.change = Decimal("0.00")
            post_completed_sale(db, sale)
            log_activity(
                db,
                user_id=reconciled_by_user_id,
                action=ActivityAction.SALE_COMPLETED,
                entity_type="sale",
                entity_id=sale.id,
                description=f"M-Pesa sale #{sale.id} confirmed by Daraja status query",
            )
            db.commit()
            db.refresh(sale)
        elif status == "failed":
            sale = release_pending_sale(
                db,
                sale.id,
                released_by_user_id=reconciled_by_user_id,
            )
        return sale
    except Exception:
        db.rollback()
        raise
