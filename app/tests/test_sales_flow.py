from datetime import datetime, timezone
from decimal import Decimal

from tests.conftest import auth_headers


def _open_session(db, user, opening_cash=Decimal("0.00")):
    from app.models.cash_session import CashSession, SessionStatus
    from app.services.cash_sessions import open_session

    if opening_cash:
        db.add(
            CashSession(
                shop_id=user.shop_id,
                user_id=user.id,
                opening_cash=Decimal("0.00"),
                closing_cash=opening_cash,
                expected_cash=opening_cash,
                difference=Decimal("0.00"),
                status=SessionStatus.CLOSED,
                closed_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    return open_session(db, user_id=user.id, shop_id=user.shop_id)


def _create_bulk_variant(client, admin_token, quantity=50000):
    headers = auth_headers(admin_token)
    product = client.post("/products", json={"name": "Sugar"}, headers=headers).json()
    variant = client.post(
        f"/products/{product['id']}/variants",
        json={
            "name": "Loose", "unit": "gram", "sale_mode": "bulk",
            "unit_quantity": 1, "selling_price": 0.14, "cost_price": 0.12,
        },
        headers=headers,
    ).json()
    client.post(
        f"/inventory/{variant['id']}/adjust",
        json={"delta": quantity, "movement_type": "purchase", "reason": "test stock"},
        headers=headers,
    )
    return variant


def test_sale_deducts_stock(client, db, admin_token, cashier_token, cashier_user):
    variant = _create_bulk_variant(client, admin_token, quantity=1000)
    opened = _open_session(db, cashier_user, Decimal("500.00"))
    assert opened.opening_cash == Decimal("500.00")

    resp = client.post(
        "/sales",
        json={"items": [{"variant_id": variant["id"], "quantity": 300}], "amount_received": 100},
        headers=auth_headers(cashier_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total"] == 42.0  # 300 * 0.14
    assert body["items"][0]["quantity"] == 300

    stock_resp = client.get("/inventory", headers=auth_headers(cashier_token))
    updated = next(v for v in stock_resp.json() if v["id"] == variant["id"])
    assert updated["quantity"] == 700  # 1000 - 300


def test_sale_without_open_session_rejected(client, admin_token, cashier_token):
    variant = _create_bulk_variant(client, admin_token, quantity=1000)
    resp = client.post(
        "/sales",
        json={"items": [{"variant_id": variant["id"], "quantity": 100}], "amount_received": 50},
        headers=auth_headers(cashier_token),
    )
    assert resp.status_code == 422
    assert "cash session" in resp.json()["detail"].lower()


def test_open_session_uses_automatic_shop_float(client, cashier_token, cashier_user):
    response = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )

    assert response.status_code == 201, response.text
    assert response.json()["shop_id"] == cashier_user.shop_id
    assert response.json()["opening_cash"] == 0.00


def test_insufficient_stock_rolls_back_completely(client, db, admin_token, cashier_token, cashier_user):
    from app.models.sale import Sale

    variant = _create_bulk_variant(client, admin_token, quantity=100)
    _open_session(db, cashier_user, Decimal("500.00"))

    sales_before = db.query(Sale).count()

    resp = client.post(
        "/sales",
        json={"items": [{"variant_id": variant["id"], "quantity": 99999}], "amount_received": 99999},
        headers=auth_headers(cashier_token),
    )
    assert resp.status_code == 422

    stock_resp = client.get("/inventory", headers=auth_headers(cashier_token))
    unchanged = next(v for v in stock_resp.json() if v["id"] == variant["id"])
    assert unchanged["quantity"] == 100  # untouched

    assert db.query(Sale).count() == sales_before  # no partial sale row created


def test_underpayment_rejected_before_stock_touched(client, db, admin_token, cashier_token, cashier_user):
    variant = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user, Decimal("500.00"))

    resp = client.post(
        "/sales",
        json={"items": [{"variant_id": variant["id"], "quantity": 100}], "amount_received": 1.0},
        headers=auth_headers(cashier_token),
    )
    assert resp.status_code == 422

    stock_resp = client.get("/inventory", headers=auth_headers(cashier_token))
    unchanged = next(v for v in stock_resp.json() if v["id"] == variant["id"])
    assert unchanged["quantity"] == 500


def test_closing_cash_above_expected_is_rejected(client, db, cashier_token, cashier_user):
    from app.models.cash_session import SessionStatus
    from app.services.cash_sessions import get_open_session

    opened = _open_session(db, cashier_user, Decimal("500.00"))

    resp = client.post(
        "/cash-sessions/close",
        json={"closing_cash": 500.01},
        headers=auth_headers(cashier_token),
    )

    assert resp.status_code == 422
    assert "cannot exceed" in resp.json()["detail"].lower()
    db.refresh(opened)
    assert opened.status == SessionStatus.OPEN
    assert opened.closing_cash is None
    assert get_open_session(db, cashier_user.shop_id) is opened


def test_closing_cash_at_or_below_expected_is_allowed(
    client, db, cashier_token, cashier_user
):
    from app.models.cash_session import SessionStatus
    from app.services.cash_sessions import get_open_session

    _open_session(db, cashier_user, Decimal("500.00"))
    for closing_cash, expected_difference in [(500.00, 0.00), (499.99, -0.01)]:
        if get_open_session(db, cashier_user.shop_id) is None:
            _open_session(db, cashier_user)
        resp = client.post(
            "/cash-sessions/close",
            json={"closing_cash": closing_cash},
            headers=auth_headers(cashier_token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == SessionStatus.CLOSED.value
        assert resp.json()["difference"] == expected_difference


def test_cashier_dashboard_shows_shop_sales_and_shared_till(
    client, db, admin_token, cashier_token, cashier_user
):
    from app.models.user import User, UserRole
    from app.services.cash_sessions import close_session
    from tests.conftest import _login

    variant = _create_bulk_variant(client, admin_token, quantity=500)
    shared_session = _open_session(db, cashier_user, Decimal("100.00"))
    sale_response = client.post(
        "/sales",
        json={
            "items": [{"variant_id": variant["id"], "quantity": 10}],
            "amount_received": 10,
        },
        headers=auth_headers(cashier_token),
    )
    assert sale_response.status_code == 201, sale_response.text

    open_summary = client.get(
        "/dashboard/cashier-summary", headers=auth_headers(cashier_token)
    )
    assert open_summary.status_code == 200, open_summary.text
    assert open_summary.json()["current_session"]["id"] == shared_session.id

    other_user = User(
        shop_id=cashier_user.shop_id,
        full_name="Other Cashier",
        username="other-cashier",
        password_hash="not-used",
        role=UserRole.CASHIER,
    )
    db.add(other_user)
    db.commit()
    other_token = _login(client, other_user.username)
    current_response = client.get(
        "/cash-sessions/current", headers=auth_headers(other_token)
    )
    assert current_response.status_code == 200
    assert current_response.json()["id"] == shared_session.id
    assert current_response.json()["opening_cash"] == 100.00
    duplicate_open = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(other_token)
    )
    assert duplicate_open.status_code == 422

    other_sale = client.post(
        "/sales",
        json={
            "items": [{"variant_id": variant["id"], "quantity": 10}],
            "amount_received": 10,
        },
        headers=auth_headers(other_token),
    )
    assert other_sale.status_code == 201, other_sale.text

    close_session(db, shared_session, closing_cash=Decimal("100.00"))
    assert shared_session.difference == Decimal("-2.80")
    next_session = _open_session(db, other_user)
    assert next_session.opening_cash == Decimal("100.00")

    from app.models.sale import Sale

    shared_sale_ids = {sale_response.json()["id"], other_sale.json()["id"]}
    assert {
        sale.session_id
        for sale in db.query(Sale).filter(Sale.id.in_(shared_sale_ids)).all()
    } == {shared_session.id}

    response = client.get(
        "/dashboard/cashier-summary", headers=auth_headers(cashier_token)
    )
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["transaction_count"] == 2
    assert summary["total_sales"] == 2.8
    assert {sale["id"] for sale in summary["recent_sales"]} == {
        sale_response.json()["id"],
        other_sale.json()["id"],
    }
    assert [session["user_id"] for session in summary["recent_sessions"]] == [
        cashier_user.id
    ]
    assert summary["recent_sessions"][0]["difference"] == -2.8
    assert summary["current_session"]["id"] == next_session.id

    today_response = client.get(
        "/sales/today", headers=auth_headers(cashier_token)
    )
    assert today_response.status_code == 200
    assert {sale["id"] for sale in today_response.json()} == {
        sale_response.json()["id"],
        other_sale.json()["id"],
    }

    sessions_response = client.get(
        f"/cash-sessions?user_id={other_user.id}",
        headers=auth_headers(cashier_token),
    )
    assert sessions_response.status_code == 200
    assert {session["user_id"] for session in sessions_response.json()} == {
        cashier_user.id,
        other_user.id,
    }