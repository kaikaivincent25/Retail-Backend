from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.activity_log import ActivityAction
from app.models.customer import Customer
from app.models.customer_payment import CustomerPayment
from app.models.sale import PaymentMethod, Sale, SaleStatus
from app.services.accounting import post_customer_payment
from app.services.audit import log_activity
from app.services.cash_sessions import get_open_session


class CustomerPaymentError(Exception):
    """Raised for any validation failure when recording customer credit repayments."""


def calculate_customer_outstanding(db: Session, shop_id: int, customer_id: int) -> tuple[Decimal, Decimal]:
    """Return (outstanding_balance, overdue_balance) for a customer."""
    today = date.today()
    sales = db.scalars(
        select(Sale)
        .options(selectinload(Sale.payments))
        .where(
            Sale.shop_id == shop_id,
            Sale.customer_id == customer_id,
            Sale.is_credit.is_(True),
            Sale.status == SaleStatus.COMPLETED,
        )
    ).all()

    outstanding = Decimal("0.00")
    overdue = Decimal("0.00")
    for sale in sales:
        paid = sum((payment.amount for payment in sale.payments), Decimal("0.00"))
        bal = max(sale.total - paid, Decimal("0.00"))
        if bal > 0:
            outstanding += bal
            if sale.due_date and sale.due_date < today:
                overdue += bal
    return outstanding, overdue


def get_customer_ledger(db: Session, shop_id: int, customer_id: int) -> dict:
    customer = db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.shop_id == shop_id)
    )
    if customer is None:
        raise CustomerPaymentError("Customer not found")

    today = date.today()
    sales = db.scalars(
        select(Sale)
        .options(selectinload(Sale.payments))
        .where(
            Sale.shop_id == shop_id,
            Sale.customer_id == customer_id,
            Sale.is_credit.is_(True),
            Sale.status == SaleStatus.COMPLETED,
        )
        .order_by(Sale.created_at.desc(), Sale.id.desc())
    ).all()

    invoices = []
    total_credit_sales = Decimal("0.00")
    total_payments = Decimal("0.00")
    outstanding_balance = Decimal("0.00")
    overdue_balance = Decimal("0.00")

    for sale in sales:
        total_credit_sales += sale.total
        paid = sum((p.amount for p in sale.payments), Decimal("0.00"))
        total_payments += paid
        bal = max(sale.total - paid, Decimal("0.00"))
        if bal > 0:
            outstanding_balance += bal
            if sale.due_date and sale.due_date < today:
                overdue_balance += bal
                status = "overdue"
            elif paid > 0:
                status = "partially_paid"
            else:
                status = "unpaid"
        else:
            status = "paid"

        invoices.append(
            {
                "id": sale.id,
                "sale_id": sale.id,
                "created_at": sale.created_at,
                "due_date": sale.due_date,
                "total": sale.total,
                "amount_paid": paid,
                "balance": bal,
                "status": status,
            }
        )

    all_payments = db.scalars(
        select(CustomerPayment)
        .options(selectinload(CustomerPayment.recorded_by))
        .where(CustomerPayment.shop_id == shop_id, CustomerPayment.customer_id == customer_id)
        .order_by(CustomerPayment.created_at.desc(), CustomerPayment.id.desc())
    ).all()

    payments_data = [
        {
            "id": p.id,
            "shop_id": p.shop_id,
            "customer_id": p.customer_id,
            "sale_id": p.sale_id,
            "session_id": p.session_id,
            "amount": p.amount,
            "payment_method": p.payment_method,
            "reference": p.reference,
            "recorded_by_user_id": p.recorded_by_user_id,
            "recorded_by_name": p.recorded_by.full_name if p.recorded_by else None,
            "created_at": p.created_at,
        }
        for p in all_payments
    ]

    return {
        "customer": customer,
        "total_credit_sales": total_credit_sales,
        "total_payments": total_payments,
        "outstanding_balance": outstanding_balance,
        "overdue_balance": overdue_balance,
        "invoices": invoices,
        "payments": payments_data,
    }


def record_customer_payment(
    db: Session,
    *,
    shop_id: int,
    user_id: int,
    customer_id: int,
    sale_id: int,
    amount: Decimal,
    payment_method: PaymentMethod,
    reference: str | None = None,
    session_id: int | None = None,
) -> CustomerPayment:
    if amount <= 0:
        raise CustomerPaymentError("Payment amount must be greater than zero")
    if amount.quantize(Decimal("0.01")) != amount:
        raise CustomerPaymentError("Payment amount must have at most two decimal places")

    # Lock customer and sale
    customer = db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.shop_id == shop_id).with_for_update()
    )
    if customer is None:
        raise CustomerPaymentError("Customer not found")

    sale = db.scalar(
        select(Sale)
        .where(
            Sale.id == sale_id,
            Sale.shop_id == shop_id,
            Sale.customer_id == customer_id,
        )
        .with_for_update()
    )
    if sale is None:
        raise CustomerPaymentError(f"Credit sale #{sale_id} not found for this customer")
    if not sale.is_credit:
        raise CustomerPaymentError("Cannot record repayments against a non-credit sale")
    if sale.status != SaleStatus.COMPLETED:
        raise CustomerPaymentError("Cannot record repayments against an incomplete sale")

    paid_so_far = db.scalar(
        select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(
            CustomerPayment.sale_id == sale.id
        )
    ) or Decimal("0.00")
    remaining_balance = sale.total - paid_so_far
    if remaining_balance <= 0:
        raise CustomerPaymentError("This invoice is already fully paid")
    if amount > remaining_balance:
        raise CustomerPaymentError(
            f"Payment amount ({amount}) exceeds remaining balance of {remaining_balance}. "
            "Overpayments are not permitted."
        )

    if payment_method == PaymentMethod.CASH:
        open_session = get_open_session(db, shop_id, lock=True)
        if open_session is None:
            raise CustomerPaymentError(
                "Open a cash session before recording a cash customer payment"
            )
        if session_id is not None and session_id != open_session.id:
            raise CustomerPaymentError(
                "Cash customer payments must be recorded in the open cash session"
            )
        session_id = open_session.id

    payment = CustomerPayment(
        shop_id=shop_id,
        customer_id=customer_id,
        sale_id=sale.id,
        session_id=session_id,
        amount=amount,
        payment_method=payment_method,
        reference=reference.strip() if reference else None,
        recorded_by_user_id=user_id,
    )
    db.add(payment)
    db.flush()

    log_activity(
        db,
        user_id=user_id,
        action=ActivityAction.SALE_COMPLETED,
        entity_type="customer_payment",
        entity_id=payment.id,
        description=f"Collected {payment.amount} for credit sale #{sale.id} via {payment.payment_method.value}",
    )

    post_customer_payment(db, payment)
    db.commit()
    db.refresh(payment)
    return payment
