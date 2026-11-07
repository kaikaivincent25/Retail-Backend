from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.customer import Customer
from app.models.user import User, UserRole
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

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
    customer = Customer(shop_id=user.shop_id, **payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


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
    for field, value in changes.items():
        setattr(customer, field, value)

    db.commit()
    db.refresh(customer)
    return customer
