from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.customer import Customer
from app.models.customer_activity import CustomerActivity
from app.models.customer_order import CustomerOrder
from app.models.sale import Sale, SaleStatus
from app.models.user import User, UserRole
from app.schemas.customer_order import CustomerOrderRead
from app.schemas.customer import (
    CustomerActivityCreate,
    CustomerActivityRead,
    CustomerActivityUpdate,
    CustomerFollowUpAssigneeRead,
    CustomerFollowUpRead,
    CustomerCreate,
    CustomerInvoiceRead,
    CustomerLedgerRead,
    CustomerPaymentCreate,
    CustomerPaymentRead,
    CustomerRead,
    CustomerTimelineEntry,
    CustomerTimelineRead,
    CustomerUpdate,
)
from app.services.accounting import AccountingError
from app.services.customer_payments import (
    CustomerPaymentError,
    get_customer_ledger,
    record_customer_payment,
)
from app.services.customer_identity import normalize_customer_phone

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=list[CustomerRead])
def list_customers(
    search: str | None = Query(default=None, max_length=150),
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = select(Customer).where(Customer.shop_id == user.shop_id)
    if not include_archived or user.role == UserRole.CASHIER:
        query = query.where(Customer.is_active.is_(True))
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Customer.full_name.ilike(term),
                Customer.phone.ilike(term),
                Customer.email.ilike(term),
            )
        )
    query = query.order_by(Customer.full_name, Customer.id).offset(offset).limit(limit)
    return db.scalars(query).all()


@router.post("", response_model=CustomerRead, status_code=201)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    customer_data = payload.model_dump()
    normalized_phone = normalize_customer_phone(customer_data["phone"])
    existing_match_count = (
        db.scalar(
            select(func.count(Customer.id)).where(
                Customer.shop_id == user.shop_id,
                Customer.phone_normalized == normalized_phone,
                Customer.is_active.is_(True),
            )
        )
        if normalized_phone
        else 0
    )
    customer = Customer(
        shop_id=user.shop_id,
        phone_normalized=normalized_phone,
        **customer_data,
    )
    db.add(customer)
    db.flush()
    if normalized_phone and existing_match_count == 0:
        db.execute(
            update(CustomerOrder)
            .where(
                CustomerOrder.shop_id == user.shop_id,
                CustomerOrder.customer_phone_normalized == normalized_phone,
                CustomerOrder.customer_id.is_(None),
            )
            .values(customer_id=customer.id)
        )
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/follow-ups/assignees", response_model=list[CustomerFollowUpAssigneeRead])
def list_customer_follow_up_assignees(
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    return db.scalars(
        select(User)
        .where(User.shop_id == user.shop_id, User.is_active.is_(True))
        .order_by(User.full_name, User.id)
    ).all()


@router.get("/follow-ups", response_model=list[CustomerFollowUpRead])
def list_customer_follow_ups(
    assigned_to_user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    if user.role == UserRole.CASHIER:
        if assigned_to_user_id is not None and assigned_to_user_id != user.id:
            raise HTTPException(status_code=403, detail="You can only view your own follow-ups")
        assigned_to_user_id = user.id
    elif assigned_to_user_id is not None:
        assignee = db.scalar(
            select(User).where(
                User.id == assigned_to_user_id,
                User.shop_id == user.shop_id,
                User.is_active.is_(True),
            )
        )
        if assignee is None:
            raise HTTPException(status_code=404, detail="Staff member not found")

    query = (
        select(CustomerActivity)
        .join(Customer, Customer.id == CustomerActivity.customer_id)
        .options(
            selectinload(CustomerActivity.customer),
            selectinload(CustomerActivity.assigned_to),
        )
        .where(
            CustomerActivity.shop_id == user.shop_id,
            CustomerActivity.activity_type == "follow_up",
            CustomerActivity.status == "open",
            CustomerActivity.due_at.is_not(None),
            Customer.is_active.is_(True),
        )
    )
    if assigned_to_user_id is not None:
        query = query.where(CustomerActivity.assigned_to_user_id == assigned_to_user_id)
    activities = db.scalars(
        query.order_by(CustomerActivity.due_at, CustomerActivity.id).limit(limit)
    ).all()
    return [
        CustomerFollowUpRead(
            id=activity.id,
            customer=activity.customer,
            body=activity.body,
            due_at=activity.due_at,
            status=activity.status,
            assigned_to_user_id=activity.assigned_to_user_id,
            assigned_to_name=activity.assigned_to.full_name if activity.assigned_to else None,
            created_at=activity.created_at,
        )
        for activity in activities
    ]


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.shop_id == user.shop_id,
        )
    )
    if customer is None or (
        user.role == UserRole.CASHIER and not customer.is_active
    ):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.get("/{customer_id}/orders", response_model=list[CustomerOrderRead])
def list_customer_order_history(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.shop_id == user.shop_id,
        )
    )
    if customer is None or (
        user.role == UserRole.CASHIER and not customer.is_active
    ):
        raise HTTPException(status_code=404, detail="Customer not found")
    return db.scalars(
        select(CustomerOrder)
        .options(selectinload(CustomerOrder.items))
        .where(
            CustomerOrder.customer_id == customer_id,
            CustomerOrder.shop_id == user.shop_id,
        )
        .order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc())
        .limit(200)
    ).all()


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.shop_id == user.shop_id,
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    if "full_name" in changes and changes["full_name"] is None:
        raise HTTPException(status_code=422, detail="Customer name cannot be empty")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=422, detail="Customer active status cannot be empty")
    previous_lead_status = customer.lead_status
    for field, value in changes.items():
        setattr(customer, field, value)
    if "phone" in changes:
        customer.phone_normalized = normalize_customer_phone(changes["phone"])
    if "lead_status" in changes and changes["lead_status"] != previous_lead_status:
        db.add(
            CustomerActivity(
                shop_id=user.shop_id,
                customer_id=customer.id,
                activity_type="lead_status",
                body=f"Lead stage changed from {previous_lead_status.replace('_', ' ').title()} to {changes['lead_status'].replace('_', ' ').title()}.",
                status="completed",
                created_by_user_id=user.id,
            )
        )

    db.commit()
    db.refresh(customer)
    return customer


def _activity_read(activity: CustomerActivity) -> CustomerActivityRead:
    return CustomerActivityRead(
        id=activity.id,
        activity_type=activity.activity_type,
        body=activity.body,
        status=activity.status,
        due_at=activity.due_at,
        completed_at=activity.completed_at,
        created_at=activity.created_at,
        created_by_user_id=activity.created_by_user_id,
        created_by_name=activity.created_by.full_name if activity.created_by else None,
        assigned_to_user_id=activity.assigned_to_user_id,
        assigned_to_name=activity.assigned_to.full_name if activity.assigned_to else None,
    )


@router.get("/{customer_id}/timeline", response_model=CustomerTimelineRead)
def get_customer_timeline(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.shop_id == user.shop_id,
        )
    )
    if customer is None or (user.role == UserRole.CASHIER and not customer.is_active):
        raise HTTPException(status_code=404, detail="Customer not found")

    entries: list[CustomerTimelineEntry] = []
    activities = db.scalars(
        select(CustomerActivity)
        .options(
            selectinload(CustomerActivity.created_by),
            selectinload(CustomerActivity.assigned_to),
        )
        .where(
            CustomerActivity.customer_id == customer_id,
            CustomerActivity.shop_id == user.shop_id,
        )
        .order_by(CustomerActivity.created_at.desc(), CustomerActivity.id.desc())
        .limit(100)
    ).all()
    for activity in activities:
        title = {
            "note": "Note",
            "follow_up": "Follow-up",
            "lead_status": "Lead stage",
        }[activity.activity_type]
        entries.append(
            CustomerTimelineEntry(
                id=f"activity-{activity.id}",
                kind=activity.activity_type,
                occurred_at=activity.created_at,
                title=title,
                details=activity.body,
                status=activity.status,
                due_at=activity.due_at,
                completed_at=activity.completed_at,
                assigned_to_name=(
                    activity.assigned_to.full_name if activity.assigned_to else None
                ),
            )
        )

    sales = db.scalars(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(
            Sale.shop_id == user.shop_id,
            Sale.customer_id == customer_id,
            Sale.status == SaleStatus.COMPLETED,
        )
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(100)
    ).all()
    linked_sale_ids = set(
        db.scalars(
            select(CustomerOrder.sale_id).where(
                CustomerOrder.shop_id == user.shop_id,
                CustomerOrder.customer_id == customer_id,
                CustomerOrder.sale_id.is_not(None),
            )
        ).all()
    )
    for sale in sales:
        if sale.id in linked_sale_ids:
            continue
        item_summary = ", ".join(
            f"{item.variant_name} × {item.quantity}" for item in sale.items
        )
        entries.append(
            CustomerTimelineEntry(
                id=f"sale-{sale.id}",
                kind="sale",
                occurred_at=sale.created_at,
                title=f"Sale #{sale.id}",
                details=item_summary or sale.payment_method.value.replace("_", " ").title(),
                status=sale.payment_method.value,
                amount=sale.total,
            )
        )

    orders = db.scalars(
        select(CustomerOrder)
        .where(
            CustomerOrder.shop_id == user.shop_id,
            CustomerOrder.customer_id == customer_id,
        )
        .order_by(CustomerOrder.created_at.desc(), CustomerOrder.id.desc())
        .limit(100)
    ).all()
    for order in orders:
        entries.append(
            CustomerTimelineEntry(
                id=f"order-{order.id}",
                kind="order",
                occurred_at=order.created_at,
                title=f"Online order {order.order_number}",
                details=order.fulfilment.value.replace("_", " ").title(),
                status=order.status.value,
                amount=order.total,
            )
        )

    entries.sort(
        key=lambda entry: (
            entry.occurred_at.replace(tzinfo=timezone.utc)
            if entry.occurred_at.tzinfo is None
            else entry.occurred_at
        ),
        reverse=True,
    )
    return CustomerTimelineRead(customer=customer, entries=entries[:100])


@router.post(
    "/{customer_id}/activities",
    response_model=CustomerActivityRead,
    status_code=201,
)
def create_customer_activity(
    customer_id: int,
    payload: CustomerActivityCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.shop_id == user.shop_id,
        )
    )
    if customer is None or (user.role == UserRole.CASHIER and not customer.is_active):
        raise HTTPException(status_code=404, detail="Customer not found")

    assigned_to_user_id = payload.assigned_to_user_id
    if payload.activity_type == "follow_up":
        assigned_to_user_id = assigned_to_user_id or user.id
        assignee = db.scalar(
            select(User).where(
                User.id == assigned_to_user_id,
                User.shop_id == user.shop_id,
                User.is_active.is_(True),
            )
        )
        if assignee is None:
            raise HTTPException(status_code=422, detail="Follow-up assignee is not active in this shop")
    elif assigned_to_user_id is not None:
        raise HTTPException(status_code=422, detail="Only follow-ups can be assigned")

    activity = CustomerActivity(
        shop_id=user.shop_id,
        customer_id=customer.id,
        activity_type=payload.activity_type,
        body=payload.body,
        status="open" if payload.activity_type == "follow_up" else "completed",
        due_at=payload.due_at,
        completed_at=None if payload.activity_type == "follow_up" else datetime.now(timezone.utc),
        created_by_user_id=user.id,
        assigned_to_user_id=assigned_to_user_id,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return _activity_read(activity)


@router.patch(
    "/{customer_id}/activities/{activity_id}",
    response_model=CustomerActivityRead,
)
def update_customer_activity(
    customer_id: int,
    activity_id: int,
    payload: CustomerActivityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    activity = db.scalar(
        select(CustomerActivity)
        .options(
            selectinload(CustomerActivity.created_by),
            selectinload(CustomerActivity.assigned_to),
        )
        .where(
            CustomerActivity.id == activity_id,
            CustomerActivity.customer_id == customer_id,
            CustomerActivity.shop_id == user.shop_id,
        )
    )
    if activity is None or (
        user.role == UserRole.CASHIER and not activity.customer.is_active
    ):
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if activity.activity_type != "follow_up":
        raise HTTPException(status_code=409, detail="Only follow-ups can be completed")
    if "assigned_to_user_id" in payload.model_fields_set:
        if user.role == UserRole.CASHIER:
            raise HTTPException(status_code=403, detail="Only managers can reassign follow-ups")
        assignee = db.scalar(
            select(User).where(
                User.id == payload.assigned_to_user_id,
                User.shop_id == user.shop_id,
                User.is_active.is_(True),
            )
        )
        if assignee is None:
            raise HTTPException(status_code=422, detail="Assignee must be active in this shop")
        activity.assigned_to_user_id = assignee.id
    if "status" in payload.model_fields_set:
        activity.status = payload.status
        activity.completed_at = (
            datetime.now(timezone.utc) if payload.status == "completed" else None
        )
    db.commit()
    db.refresh(activity)
    return _activity_read(activity)


@router.get("/{customer_id}/ledger", response_model=CustomerLedgerRead)
def get_ledger(
    customer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    try:
        return get_customer_ledger(db, user.shop_id, customer_id)
    except CustomerPaymentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{customer_id}/payments", response_model=CustomerPaymentRead, status_code=201)
def make_payment(
    customer_id: int,
    payload: CustomerPaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    try:
        payment = record_customer_payment(
            db,
            shop_id=user.shop_id,
            user_id=user.id,
            customer_id=customer_id,
            sale_id=payload.sale_id,
            amount=payload.amount,
            payment_method=payload.payment_method,
            reference=payload.reference,
        )
        return CustomerPaymentRead(
            id=payment.id,
            shop_id=payment.shop_id,
            customer_id=payment.customer_id,
            sale_id=payment.sale_id,
            session_id=payment.session_id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            reference=payment.reference,
            recorded_by_user_id=payment.recorded_by_user_id,
            recorded_by_name=user.full_name,
            created_at=payment.created_at,
        )
    except CustomerPaymentError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except AccountingError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail=f"Accounting could not post this payment: {exc}",
        ) from exc
