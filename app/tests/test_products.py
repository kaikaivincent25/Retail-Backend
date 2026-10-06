from tests.conftest import auth_headers


def test_admin_can_create_product(client, admin_token):
    resp = client.post(
        "/products", json={"name": "Sugar", "category": "Dry goods"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Sugar"


def test_admin_can_create_product_with_multiple_variants(client, admin_token):
    resp = client.post(
        "/products",
        json={
            "name": "Sugar",
            "category": "Dry goods",
            "variants": [
                {
                    "name": "1kg pack",
                    "unit": "kg",
                    "unit_quantity": 1,
                    "selling_price": 150,
                },
                {
                    "name": "Loose",
                    "unit": "gram",
                    "sale_mode": "bulk",
                    "selling_price": 0.2,
                },
            ],
        },
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Sugar"
    assert [variant["name"] for variant in body["variants"]] == ["1kg pack", "Loose"]
    assert body["variants"][1]["sale_mode"] == "bulk"
    assert body["variants"][1]["unit_quantity"] == 1


def test_duplicate_variant_names_rejected_when_creating_product(client, admin_token):
    resp = client.post(
        "/products",
        json={
            "name": "Sugar",
            "variants": [
                {"name": "1kg", "unit": "kg", "selling_price": 150},
                {"name": "1kg", "unit": "kg", "selling_price": 155},
            ],
        },
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Variant names must be unique within a product"


def test_cashier_cannot_create_product(client, cashier_token):
    resp = client.post(
        "/products", json={"name": "Sugar"}, headers=auth_headers(cashier_token)
    )
    assert resp.status_code == 403


def test_cashier_can_list_products(client, admin_token, cashier_token):
    client.post("/products", json={"name": "Milk"}, headers=auth_headers(admin_token))
    resp = client.get("/products", headers=auth_headers(cashier_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_unauthenticated_request_is_rejected(client):
    resp = client.get("/products")
    assert resp.status_code == 401


def test_popular_products_includes_active_variants_without_sales(client, admin_token, cashier_token):
    headers = auth_headers(admin_token)
    product = client.post("/products", json={"name": "Rice", "category": "Food"}, headers=headers).json()
    variant = client.post(
        f"/products/{product['id']}/variants",
        json={
            "name": "5kg",
            "unit": "kg",
            "sale_mode": "fixed",
            "unit_quantity": 5,
            "selling_price": 250.0,
            "cost_price": 200.0,
        },
        headers=headers,
    ).json()
    client.post(
        f"/inventory/{variant['id']}/adjust",
        json={"delta": 30, "movement_type": "purchase", "reason": "fresh stock"},
        headers=headers,
    )

    resp = client.get("/products/popular", headers=auth_headers(cashier_token))
    assert resp.status_code == 200
    assert any(item["variant_id"] == variant["id"] for item in resp.json())


def test_duplicate_product_name_rejected(client, admin_token):
    headers = auth_headers(admin_token)
    client.post("/products", json={"name": "Sugar"}, headers=headers)
    resp = client.post("/products", json={"name": "Sugar"}, headers=headers)
    assert resp.status_code == 409