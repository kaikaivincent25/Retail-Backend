from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product
from app.models.shop import Shop
from app.models.variant import Variant
from app.schemas.product import PublicProductRead, PublicShopRead, PublicVariantRead

router = APIRouter(prefix="/public", tags=["Public catalogue"])


def _public_product(product: Product, variants: list[Variant]) -> PublicProductRead:
    return PublicProductRead(
        id=product.id,
        name=product.public_name or product.name,
        category=product.category,
        brand=product.brand,
        description=product.public_description or product.description,
        image_url=product.public_image_url or product.image_url,
        availability_message=product.availability_message,
        variants=[
            PublicVariantRead(
                id=variant.id,
                name=variant.name,
                unit=variant.unit.value,
                sale_mode=variant.sale_mode.value,
                selling_price=variant.selling_price,
                is_available=variant.quantity > 0,
            )
            for variant in variants
        ],
    )


def _get_shop(db: Session, slug: str) -> Shop:
    shop = db.scalar(select(Shop).where(Shop.slug == slug, Shop.is_suspended.is_(False)))
    if shop is None:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


def _product_query(shop_id: int, q: str | None = None, category: str | None = None):
    query = select(Product).where(
        Product.shop_id == shop_id,
        Product.is_active.is_(True),
        Product.is_public.is_(True),
        select(Variant.id).where(
            Variant.product_id == Product.id,
            Variant.is_active.is_(True),
        ).exists(),
    )
    if q:
        search = f"%{q.strip()}%"
        query = query.where(
            or_(
                (Product.public_name.is_not(None) & Product.public_name.ilike(search)),
                Product.name.ilike(search),
                Product.category.ilike(search),
                Product.brand.ilike(search),
                Product.public_description.ilike(search),
            )
        )
    if category:
        query = query.where(Product.category == category)
    return query.order_by(Product.name)


@router.get("/shops/{slug}", response_model=PublicShopRead)
def get_public_shop(slug: str, db: Session = Depends(get_db)):
    shop = _get_shop(db, slug)
    products = db.scalars(_product_query(shop.id)).all()
    result = []
    for product in products:
        variants = db.scalars(
            select(Variant).where(Variant.product_id == product.id, Variant.is_active.is_(True))
        ).all()
        result.append(_public_product(product, variants))
    return PublicShopRead(
        name=shop.name,
        slug=shop.slug,
        location=shop.location,
        currency=shop.currency,
        business_type=shop.business_type,
        products=result,
    )


@router.get("/shops/{slug}/products", response_model=list[PublicProductRead])
def list_public_products(
    slug: str,
    q: str | None = Query(None),
    category: str | None = Query(None),
    db: Session = Depends(get_db),
):
    shop = _get_shop(db, slug)
    products = db.scalars(_product_query(shop.id, q=q, category=category)).all()
    return [
        _public_product(
            product,
            db.scalars(
                select(Variant).where(Variant.product_id == product.id, Variant.is_active.is_(True))
            ).all(),
        )
        for product in products
    ]


@router.get("/shops/{slug}/products/{product_id}", response_model=PublicProductRead)
def get_public_product(slug: str, product_id: int, db: Session = Depends(get_db)):
    shop = _get_shop(db, slug)
    product = db.scalar(_product_query(shop.id).where(Product.id == product_id))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    variants = db.scalars(
        select(Variant).where(Variant.product_id == product.id, Variant.is_active.is_(True))
    ).all()
    return _public_product(product, variants)
