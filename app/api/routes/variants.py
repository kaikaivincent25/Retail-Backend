from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_cashier, require_manager
from app.core.database import get_db
from app.models.bulk_preset import BulkPreset
from app.models.product import Product
from app.models.user import User
from app.models.variant import Variant
from app.schemas.bulk_preset import BulkPresetCreate, BulkPresetRead
from app.schemas.product import VariantBrowseResult
from app.schemas.variant import VariantCreate, VariantRead, VariantUpdate

router = APIRouter(tags=["Variants"])


def get_owned_product(db: Session, product_id: int, shop_id: int) -> Product:
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.shop_id == shop_id)
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def get_owned_variant(db: Session, variant_id: int, shop_id: int) -> Variant:
    variant = db.scalar(
        select(Variant)
        .join(Product)
        .where(Variant.id == variant_id, Product.shop_id == shop_id)
    )
    if variant is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return variant


def _preset_to_read(preset: BulkPreset, variant: Variant) -> BulkPresetRead:
    return BulkPresetRead(
        id=preset.id,
        variant_id=preset.variant_id,
        label=preset.label,
        amount=preset.amount,
        price=round(float(variant.selling_price) * preset.amount, 2),
        is_active=preset.is_active,
    )


@router.post(
    "/products/{product_id}/variants",
    response_model=VariantRead,
    status_code=status.HTTP_201_CREATED,
)
def create_variant(
    product_id: int,
    payload: VariantCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    get_owned_product(db, product_id, user.shop_id)  # 404s if not yours

    if payload.sku and db.scalar(select(Variant).where(Variant.sku == payload.sku)):
        raise HTTPException(status_code=409, detail=f"SKU '{payload.sku}' already in use")

    variant = Variant(product_id=product_id, **payload.model_dump())
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


@router.get("/products/{product_id}/variants", response_model=list[VariantRead])
def list_variants_for_product(
    product_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    get_owned_product(db, product_id, user.shop_id)

    query = select(Variant).where(Variant.product_id == product_id)
    if not (include_inactive and user.role.value in ("admin", "manager")):
        query = query.where(Variant.is_active.is_(True))

    return db.scalars(query.order_by(Variant.name)).all()


@router.get("/variants", response_model=list[VariantBrowseResult])
def browse_variants(
    q: str | None = Query(None, description="Search by product or variant name"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
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
        )
        .join(Product, Product.id == Variant.product_id)
        .where(Product.shop_id == user.shop_id, Variant.is_active.is_(True))
    )

    if q:
        query = query.where(
            or_(Variant.name.ilike(f"%{q}%"), Product.name.ilike(f"%{q}%"))
        )

    rows = db.execute(query.order_by(Product.name, Variant.name).limit(limit)).all()
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
                    id=preset.id,
                    variant_id=preset.variant_id,
                    label=preset.label,
                    amount=preset.amount,
                    price=round(float(r.selling_price) * preset.amount, 2),
                    is_active=True,
                )
                for preset in preset_rows
            ]

        results.append(
            VariantBrowseResult(
                variant_id=r.variant_id,
                variant_name=r.variant_name,
                product_id=r.product_id,
                product_name=r.product_name,
                unit=r.unit.value,
                sale_mode=r.sale_mode.value,
                selling_price=float(r.selling_price),
                quantity_in_stock=int(r.quantity_in_stock),
                presets=presets,
            )
        )
    return results


@router.post(
    "/variants/{variant_id}/presets",
    response_model=BulkPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_preset(
    variant_id: int,
    payload: BulkPresetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    variant = get_owned_variant(db, variant_id, user.shop_id)
    if variant.sale_mode.value != "bulk":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Presets only apply to bulk (measured) variants",
        )

    preset = BulkPreset(
        variant_id=variant_id,
        label=payload.label,
        amount=payload.amount,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _preset_to_read(preset, variant)


@router.get(
    "/variants/{variant_id}/presets",
    response_model=list[BulkPresetRead],
)
def list_presets(
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_cashier),
):
    variant = get_owned_variant(db, variant_id, user.shop_id)
    presets = db.scalars(
        select(BulkPreset)
        .where(
            BulkPreset.variant_id == variant_id,
            BulkPreset.is_active.is_(True),
        )
        .order_by(BulkPreset.amount)
    ).all()
    return [_preset_to_read(preset, variant) for preset in presets]


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    preset = db.scalar(
        select(BulkPreset)
        .join(Variant)
        .join(Product)
        .where(
            BulkPreset.id == preset_id,
            Product.shop_id == user.shop_id,
        )
    )
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    preset.is_active = False
    db.commit()


@router.patch("/variants/{variant_id}", response_model=VariantRead)
def update_variant(
    variant_id: int,
    payload: VariantUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    variant = get_owned_variant(db, variant_id, user.shop_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)

    db.commit()
    db.refresh(variant)
    return variant


@router.delete("/variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variant(
    variant_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_manager),
):
    variant = get_owned_variant(db, variant_id, user.shop_id)
    variant.is_active = False
    db.commit()