import pytest
from pydantic import ValidationError

from app.schemas.product import ProductCreate
from app.schemas.shop import ShopUpdate


@pytest.mark.parametrize("sales_group", ["breakfast", "everyday", "evening"])
def test_product_sales_group_accepts_supported_values(sales_group):
    product = ProductCreate(name="Tea", sales_group=sales_group)

    assert product.sales_group == sales_group


def test_product_sales_group_is_optional_and_rejects_unknown_values():
    assert ProductCreate(name="Tea").sales_group is None

    with pytest.raises(ValidationError):
        ProductCreate(name="Tea", sales_group="snacks")


def test_shop_sales_schedule_requires_breakfast_before_evening():
    schedule = ShopUpdate(
        breakfast_start_minute=360,
        breakfast_end_minute=630,
        evening_start_minute=960,
    )

    assert schedule.evening_start_minute == 960
    with pytest.raises(ValidationError):
        ShopUpdate(
            breakfast_start_minute=600,
            breakfast_end_minute=480,
            evening_start_minute=960,
        )
