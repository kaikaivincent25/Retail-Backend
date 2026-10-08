from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.bulk_preset import BulkPreset
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.models.variant import Variant
from app.schemas.bulk_preset import BulkPresetRead
from app.schemas.product import (
    PopularVariant,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ProductWithVariantsRead,
    VariantRead,
)

router = APIRouter(prefix="/products", tags=["Products"])


def get_product_or_404(db: Session, product_id: int, shop_id: int) -> Product:
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def ensure_name_free(
    db: Session, shop_id: int, name: str, exclude_id: int | None = None
) -> None:
    query = select(Product).where(Product.shop_id == shop_id, Product.name == name)
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(
            status_code=409,
            detail=f"A product named '{name}' already exists (it may be deactivated)",
        )


@router.post("", response_model=ProductWithVariantsRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    ensure_name_free(db, user.shop_id, payload.name)
    variant_names = [variant.name for variant in payload.variants]
    if len(variant_names) != len(set(variant_names)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Variant names must be unique within a product",
        )

    skus = [variant.sku for variant in payload.variants if variant.sku]
    if len(skus) != len(set(skus)) or any(
        db.scalar(select(Variant).where(Variant.sku == sku)) for sku in skus
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more variant SKUs are already in use",
        )

    product = Product(
        shop_id=user.shop_id,
        **payload.model_dump(exclude={"variants"}),
    )
    db.add(product)
    db.flush()

    variants = [
        Variant(product_id=product.id, **variant.model_dump())
        for variant in payload.variants
    ]
    db.add_all(variants)
    db.commit()
    db.refresh(product)
    for variant in variants:
        db.refresh(variant)
    return ProductWithVariantsRead(
        **ProductRead.model_validate(product).model_dump(),
        variants=[VariantRead.model_validate(variant) for variant in variants],
    )

@router.get("/popular", response_model=list[PopularVariant])
def popular_products(
    limit: int = Query(12, ge=1, le=50),
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_quantity_sold = func.coalesce(
        func.sum(case((Sale.created_at >= since, SaleItem.quantity), else_=0)),
        0,
    ).label("total_quantity_sold")

    query = (
        select(
            Variant.id.label("variant_id"),
            Variant.name.label("variant_name"),
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Variant.unit,
            Variant.sale_mode,
            Variant.selling_price,
            Variant.quantity.label("quantity_in_stock"),
            total_quantity_sold,
        )
        .join(Product, Product.id == Variant.product_id)
        .outerjoin(SaleItem, SaleItem.variant_id == Variant.id)
        .outerjoin(Sale, Sale.id == SaleItem.sale_id)
        .where(
            Product.shop_id == user.shop_id,
            Product.is_active.is_(True),
            Variant.is_active.is_(True),
        )
        .group_by(
            Variant.id, Variant.name, Product.id, Product.name,
            Variant.unit, Variant.sale_mode, Variant.selling_price, Variant.quantity,
        )
        .order_by(total_quantity_sold.desc(), Variant.name.asc())
        .limit(limit)
    )

    rows = db.execute(query).all()
    results = []
    for r in rows:
        presets = []
        if r.sale_mode.value == "bulk":
            preset_rows = db.scalars(
                select(BulkPreset)
                .where(
                    BulkPreset.variant_id == r.variant_id,
                    BulkPreset.is_active.is_(True),
                )
                .order_by(BulkPreset.amount)
            ).all()
            presets = [
                BulkPresetRead(
                    id=p.id,
                    variant_id=p.variant_id,
                    label=p.label,
                    amount=p.amount,
                    price=round(float(r.selling_price) * p.amount, 2),
                    is_active=True,
                )
                for p in preset_rows
            ]

        results.append(
            PopularVariant(
                variant_id=r.variant_id,
                variant_name=r.variant_name,
                product_id=r.product_id,
                product_name=r.product_name,
                unit=r.unit.value,
                sale_mode=r.sale_mode.value,
                selling_price=r.selling_price,
                quantity_in_stock=int(r.quantity_in_stock),
                total_quantity_sold=int(r.total_quantity_sold),
                presets=presets,
            )
        )
    return results

@router.get("", response_model=list[ProductRead])
def list_products(
    q: str | None = Query(None, description="Search by name"),
    category: str | None = None,
    include_inactive: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    query = select(Product).where(Product.shop_id == user.shop_id)

    # Only managers/admins may see deactivated products
    if not (include_inactive and user.role.value in ("admin", "manager")):
        query = query.where(Product.is_active.is_(True))

    if q:
        query = query.where(Product.name.ilike(f"%{q}%"))
    if category:
        query = query.where(Product.category == category)

    query = query.order_by(Product.name).offset(skip).limit(limit)
    return db.scalars(query).all()


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    product = get_product_or_404(db, product_id, user.shop_id)
    if not product.is_active and user.role.value == "cashier":
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    product = get_product_or_404(db, product_id, user.shop_id)

    # Explicit nulls are only allowed for category (to clear it)
    data = {
        k: v
        for k, v in payload.model_dump(exclude_unset=True).items()
        if v is not None or k == "category"
    }

    if "name" in data:
        name = data["name"]
        if isinstance(name, str):
            ensure_name_free(db, user.shop_id, name, exclude_id=product.id)

    for field, value in data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/reactivate", response_model=ProductRead)
def reactivate_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    product = get_product_or_404(db, product_id, user.shop_id)
    product.is_active = True
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    """Soft delete: the row stays, it is just deactivated."""
    product = get_product_or_404(db, product_id, user.shop_id)
    product.is_active = False
    db.commit()


@router.delete("/{product_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def permanently_delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    product = get_product_or_404(db, product_id, user.shop_id)
    if product.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deactivate the product before permanently deleting it",
        )

    variant_ids = db.scalars(
        select(Variant.id).where(Variant.product_id == product.id)
    ).all()
    if variant_ids:
        has_sales = db.scalar(
            select(SaleItem.id)
            .where(SaleItem.variant_id.in_(variant_ids))
            .limit(1)
        )
        has_stock_movements = db.scalar(
            select(StockMovement.id)
            .where(StockMovement.variant_id.in_(variant_ids))
            .limit(1)
        )
        if has_sales or has_stock_movements:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This product has sales or stock history and cannot be "
                    "permanently deleted. Keep it deactivated instead."
                ),
            )

        db.execute(
            delete(BulkPreset).where(BulkPreset.variant_id.in_(variant_ids))
        )
        db.execute(delete(Variant).where(Variant.id.in_(variant_ids)))

    db.delete(product)
    db.commit()