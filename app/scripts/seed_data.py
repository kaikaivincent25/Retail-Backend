import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.cash_session import CashSession, SessionStatus
from app.models.product import Product
from app.models.sale import PaymentMethod, Sale, SaleItem, SaleStatus
from app.models.shop import Shop
from app.models.stock_movement import MovementType, StockMovement
from app.models.user import User, UserRole
from app.models.variant import SaleMode, Unit, Variant

SHOP_NAME = "Vincent Household & Grocery"

# (product_name, category, [ (variant_name, unit, sale_mode, unit_quantity, selling_price, cost_price, opening_stock) ])
CATALOG = [
    ("Sugar", "Dry goods", [
        ("Kabras 1kg", Unit.KG, SaleMode.FIXED, 1, 140, 120, 40),
        ("Kabras 2kg", Unit.KG, SaleMode.FIXED, 2, 270, 235, 20),
        ("Mumias 1kg", Unit.KG, SaleMode.FIXED, 1, 138, 118, 30),
        ("Loose", Unit.GRAM, SaleMode.BULK, 1, 0.14, 0.12, 50000),
    ]),
    ("Cooking Fat", "Dry goods", [
        ("Kimbo 500g", Unit.GRAM, SaleMode.FIXED, 500, 180, 155, 25),
        ("Loose", Unit.GRAM, SaleMode.BULK, 1, 0.38, 0.32, 10000),
    ]),
    ("Milk", "Fresh", [
        ("Brookside 500ml", Unit.ML, SaleMode.FIXED, 500, 60, 50, 40),
        ("Brookside 1 litre", Unit.LITRE, SaleMode.FIXED, 1, 110, 95, 20),
    ]),
    ("Bread", "Bakery", [
        ("Supaloaf 400g", Unit.PIECE, SaleMode.FIXED, 1, 65, 55, 30),
    ]),
    ("Cooking Oil", "Dry goods", [
        ("Fresh Fri 1 litre", Unit.LITRE, SaleMode.FIXED, 1, 320, 285, 15),
        ("Loose", Unit.ML, SaleMode.BULK, 1, 0.33, 0.28, 8000),
    ]),
    ("Rice", "Dry goods", [
        ("Pishori 2kg", Unit.KG, SaleMode.FIXED, 2, 380, 330, 15),
        ("Loose", Unit.GRAM, SaleMode.BULK, 1, 0.19, 0.16, 30000),
    ]),
    ("Airtime", "Services", [
        ("Safaricom KSh 50", Unit.PIECE, SaleMode.FIXED, 1, 50, 48, 100),
    ]),
    ("Soap", "Household", [
        ("Omo 1kg", Unit.KG, SaleMode.FIXED, 1, 230, 200, 20),
    ]),
]


def main():
    db = SessionLocal()

    if db.scalar(select(Shop).where(Shop.name == SHOP_NAME)):
        print(f"'{SHOP_NAME}' already exists — refusing to seed twice. "
              f"Drop/reset the database first if you want a fresh seed.")
        db.close()
        return

    print(f"Creating shop '{SHOP_NAME}'...")
    shop = Shop(name=SHOP_NAME, location="Nairobi", currency="KES")
    db.add(shop)
    db.flush()

    print("Creating staff...")
    admin = User(
        shop_id=shop.id, full_name="Kaikai Vincent", username="admin",
        password_hash=hash_password("admin123"), role=UserRole.ADMIN,
    )
    cashier1 = User(
        shop_id=shop.id, full_name="Grace Wanjiru", username="cashier1",
        password_hash=hash_password("cashier123"), role=UserRole.CASHIER,
    )
    cashier2 = User(
        shop_id=shop.id, full_name="Peter Otieno", username="cashier2",
        password_hash=hash_password("cashier123"), role=UserRole.CASHIER,
    )
    db.add_all([admin, cashier1, cashier2])
    db.flush()

    print("Creating products, variants, and opening stock...")
    all_variants = []  # (variant_obj,)
    for product_name, category, variant_rows in CATALOG:
        product = Product(shop_id=shop.id, name=product_name, category=category)
        db.add(product)
        db.flush()

        for name, unit, sale_mode, unit_qty, price, cost, opening_stock in variant_rows:
            variant = Variant(
                product_id=product.id, name=name, unit=unit, sale_mode=sale_mode,
                unit_quantity=unit_qty, selling_price=price, cost_price=cost,
                quantity=opening_stock, reorder_level=max(int(opening_stock * 0.1), 5),
            )
            db.add(variant)
            db.flush()

            db.add(StockMovement(
                variant_id=variant.id, movement_type=MovementType.PURCHASE,
                quantity=opening_stock, previous_quantity=0, new_quantity=opening_stock,
                reason="Initial stock", user_id=admin.id,
            ))
            all_variants.append(variant)

    db.commit()
    print(f"  {len(all_variants)} variants created across {len(CATALOG)} products.")

    print("Generating sales history over the last 14 days...")
    random.seed(42)  # reproducible seed data
    cashiers = [cashier1, cashier2]
    sale_count = 0

    for days_ago in range(14, 0, -1):
        sale_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
        daily_transactions = random.randint(8, 20)

        for _ in range(daily_transactions):
            cashier = random.choice(cashiers)
            num_items = random.randint(1, 3)
            chosen_variants = random.sample(all_variants, min(num_items, len(all_variants)))

            subtotal = Decimal("0")
            sale = Sale(
                shop_id=shop.id, cashier_id=cashier.id,
                subtotal=Decimal("0"), total=Decimal("0"), amount_received=Decimal("0"), change=Decimal("0"),
                payment_method=PaymentMethod.CASH, status=SaleStatus.COMPLETED,
            )
            # Backdate created_at manually after flush, since server_default would stamp "now"
            db.add(sale)
            db.flush()

            for variant in chosen_variants:
                if variant.sale_mode == SaleMode.BULK:
                    qty = random.choice([100, 150, 200, 250, 300, 500])
                else:
                    qty = random.randint(1, 2)

                if qty > variant.quantity:
                    continue  # skip if seed stock can't cover it (keeps totals honest)

                line_total = (Decimal(str(variant.selling_price)) * qty).quantize(Decimal("0.01"))
                subtotal += line_total
                variant.quantity -= qty

                db.add(SaleItem(
                    sale_id=sale.id, variant_id=variant.id, variant_name=variant.name,
                    quantity=qty, unit_price=variant.selling_price, line_total=line_total,
                ))
                db.add(StockMovement(
                    variant_id=variant.id, movement_type=MovementType.SALE,
                    quantity=-qty, previous_quantity=variant.quantity + qty,
                    new_quantity=variant.quantity, reason=f"Sale #{sale.id}", user_id=cashier.id,
                ))

            if subtotal == 0:
                db.delete(sale)
                continue

            total = subtotal.quantize(Decimal("0.01"))
            received = total + Decimal(random.choice([0, 0, 0, 50, 100]))  # usually exact, sometimes rounded up
            sale.subtotal = total
            sale.total = total
            sale.amount_received = received
            sale.change = received - total
            sale.created_at = sale_date
            sale_count += 1

    db.commit()
    print(f"  {sale_count} historical sales created.")

    print("\nSeed complete.")
    print(f"  Shop: {SHOP_NAME}")
    print(f"  Admin login:    admin / admin123")
    print(f"  Cashier login:  cashier1 / cashier123")
    print(f"  Cashier login:  cashier2 / cashier123")
    db.close()


if __name__ == "__main__":
    main()