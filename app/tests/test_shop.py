from app.models.shop import Shop
from tests.conftest import auth_headers


def test_admin_can_get_shop(client, admin_token, shop):
    response = client.get("/shop", headers=auth_headers(admin_token))

    assert response.status_code == 200
    assert response.json() == {
        "id": shop.id,
        "name": "Test Duka",
        "location": None,
        "currency": "KES",
    }


def test_admin_can_update_shop(client, admin_token):
    response = client.patch(
        "/shop",
        json={"name": "Updated Duka", "location": "Nairobi", "currency": "USD"},
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Duka"
    assert response.json()["location"] == "Nairobi"
    assert response.json()["currency"] == "USD"


def test_shop_name_can_remain_unchanged(client, admin_token):
    response = client.patch(
        "/shop",
        json={"name": "Test Duka"},
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Test Duka"


def test_admin_cannot_rename_shop_to_another_shop_name(client, db, admin_token):
    db.add(Shop(name="Another Duka", currency="KES"))
    db.commit()

    response = client.patch(
        "/shop",
        json={"name": "Another Duka"},
        headers=auth_headers(admin_token),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A shop named 'Another Duka' already exists"


def test_cashier_cannot_access_shop_settings(client, cashier_token):
    response = client.get("/shop", headers=auth_headers(cashier_token))

    assert response.status_code == 403
