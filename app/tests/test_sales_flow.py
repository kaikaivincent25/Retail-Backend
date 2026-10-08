from datetime import date, datetime, timezone
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


def _start_mpesa_sale(client, db, admin_token, cashier_token, cashier_user, monkeypatch, quantity=100):
    from app.models.variant import Variant

    variant = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user, Decimal("500.00"))
    requested = {}

    def fake_stk_push(sale_id, amount, phone_number):
        requested.update(
            sale_id=sale_id,
            amount=amount,
            phone_number=phone_number,
        )
        return {
            "checkout_request_id": f"ws_CO_{sale_id}",
            "merchant_request_id": f"mr_{sale_id}",
        }

    monkeypatch.setattr("app.api.routes.sales.request_stk_push", fake_stk_push)
    response = client.post(
        "/sales/mpesa",
        json={
            "items": [{"variant_id": variant["id"], "quantity": quantity}],
            "phone_number": "0712345678",
            "amount": 0.01,
        },
        headers=auth_headers(cashier_token),
    )
    return response, requested, db.get(Variant, variant["id"])


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


def test_mpesa_stk_uses_server_total_and_completes_only_on_matching_callback(
    client, db, admin_token, cashier_token, cashier_user, monkeypatch
):
    response, requested, variant = _start_mpesa_sale(
        client, db, admin_token, cashier_token, cashier_user, monkeypatch
    )
    assert response.status_code == 202, response.text
    sale = response.json()
    assert sale["total"] == 14.0
    assert sale["amount_received"] == 0.0
    assert sale["payment_method"] == "mpesa"
    assert sale["status"] == "pending"
    assert requested["amount"] == Decimal("14.00")
    assert requested["phone_number"] == "254712345678"
    db.refresh(variant)
    assert variant.quantity == 400

    callback = client.post(
        "/sales/mpesa/callback",
        json={
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": requested["merchant_request_id"],
                    "CheckoutRequestID": requested["checkout_request_id"],
                    "ResultCode": 0,
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 14},
                            {"Name": "MpesaReceiptNumber", "Value": "QGH123ABC"},
                            {"Name": "PhoneNumber", "Value": 254712345678},
                        ]
                    },
                }
            }
        },
    )
    assert callback.status_code == 200, callback.text
    detail = client.get(f"/sales/{sale['id']}", headers=auth_headers(cashier_token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "completed"
    assert detail.json()["amount_received"] == 14.0
    assert detail.json()["mpesa_receipt_number"] == "QGH123ABC"
    db.refresh(variant)
    assert variant.quantity == 400


def test_failed_mpesa_callback_releases_reserved_stock(
    client, db, admin_token, cashier_token, cashier_user, monkeypatch
):
    response, requested, variant = _start_mpesa_sale(
        client, db, admin_token, cashier_token, cashier_user, monkeypatch
    )
    assert response.status_code == 202, response.text

    callback = client.post(
        "/sales/mpesa/callback",
        json={
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": requested["merchant_request_id"],
                    "CheckoutRequestID": requested["checkout_request_id"],
                    "ResultCode": 1032,
                    "ResultDesc": "Request cancelled by user",
                }
            }
        },
    )
    assert callback.status_code == 200, callback.text
    detail = client.get(
        f"/sales/{response.json()['id']}",
        headers=auth_headers(cashier_token),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "failed"
    db.refresh(variant)
    assert variant.quantity == 500


def test_mpesa_fractional_total_is_rejected_without_stock_change(
    client, db, admin_token, cashier_token, cashier_user, monkeypatch
):
    variant_data = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user, Decimal("500.00"))
    stk_called = False

    def fake_stk_push(*args):
        nonlocal stk_called
        stk_called = True
        return {}

    monkeypatch.setattr("app.api.routes.sales.request_stk_push", fake_stk_push)
    response = client.post(
        "/sales/mpesa",
        json={
            "items": [{"variant_id": variant_data["id"], "quantity": 1}],
            "phone_number": "0712345678",
        },
        headers=auth_headers(cashier_token),
    )
    assert response.status_code == 422
    assert not stk_called
    from app.models.variant import Variant

    assert db.get(Variant, variant_data["id"]).quantity == 500


def test_manual_mpesa_payment_is_pending_until_cashier_confirms_receipt(
    client, db, admin_token, cashier_token, cashier_user
):
    from app.models.variant import Variant

    variant = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user, Decimal("500.00"))
    admin_headers = auth_headers(admin_token)
    cashier_headers = auth_headers(cashier_token)
    configured = client.patch(
        "/shop",
        json={
            "mpesa_pochi_number": "0711222333",
            "mpesa_paybill_number": "123456",
            "mpesa_paybill_account_number": "SHOP-001",
        },
        headers=admin_headers,
    )
    assert configured.status_code == 200, configured.text

    destinations = client.get("/shop/payment-destinations", headers=cashier_headers)
    assert destinations.status_code == 200, destinations.text
    assert [option["method"] for option in destinations.json()] == ["pochi", "paybill"]

    response = client.post(
        "/sales/manual-mpesa",
        json={
            "items": [{"variant_id": variant["id"], "quantity": 100}],
            "payment_method": "paybill",
        },
        headers=cashier_headers,
    )
    assert response.status_code == 202, response.text
    pending_sale = response.json()
    assert pending_sale["status"] == "pending"
    assert pending_sale["payment_method"] == "paybill"
    assert pending_sale["amount_received"] == 0
    assert pending_sale["payment_destination_number"] == "123456"
    assert pending_sale["payment_account_number"] == "SHOP-001"

    db.refresh(db.get(Variant, variant["id"]))
    assert db.get(Variant, variant["id"]).quantity == 400

    confirmation = client.post(
        f"/sales/{pending_sale['id']}/manual-payment/confirm",
        json={"receipt_number": " QGH123ABC "},
        headers=cashier_headers,
    )
    assert confirmation.status_code == 200, confirmation.text
    completed_sale = confirmation.json()
    assert completed_sale["status"] == "completed"
    assert completed_sale["amount_received"] == completed_sale["total"]
    assert completed_sale["mpesa_receipt_number"] == "QGH123ABC"
    assert completed_sale["payment_destination_number"] == "123456"
    assert client.post(
        f"/sales/{pending_sale['id']}/manual-payment/confirm",
        json={"receipt_number": "QGH123ABC"},
        headers=cashier_headers,
    ).status_code == 200


def test_cancelled_manual_mpesa_sale_releases_reserved_stock(
    client, db, admin_token, cashier_token, cashier_user
):
    from app.models.variant import Variant

    variant = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user)
    configured = client.patch(
        "/shop",
        json={"mpesa_till_number": "998877"},
        headers=auth_headers(admin_token),
    )
    assert configured.status_code == 200, configured.text

    pending = client.post(
        "/sales/manual-mpesa",
        json={
            "items": [{"variant_id": variant["id"], "quantity": 100}],
            "payment_method": "till",
        },
        headers=auth_headers(cashier_token),
    )
    assert pending.status_code == 202, pending.text
    cancelled = client.post(
        f"/sales/{pending.json()['id']}/manual-payment/cancel",
        headers=auth_headers(cashier_token),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "failed"
    db.refresh(db.get(Variant, variant["id"]))
    assert db.get(Variant, variant["id"]).quantity == 500


def test_paybill_settings_require_account_number(client, admin_token):
    response = client.patch(
        "/shop",
        json={"mpesa_paybill_number": "123456"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 422
    assert "account number" in response.json()["detail"].lower()


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


def test_staff_consumption_reduces_stock_but_not_expected_cash(
    client, db, admin_token, cashier_token, cashier_user
):
    from app.models.stock_movement import MovementType, StockMovement
    from app.models.variant import Variant

    variant_data = _create_bulk_variant(client, admin_token, quantity=500)
    _open_session(db, cashier_user, Decimal("100.00"))

    bypass = client.post(
        f"/inventory/{variant_data['id']}/adjust",
        json={"delta": -10, "movement_type": "staff_consumption"},
        headers=auth_headers(admin_token),
    )
    assert bypass.status_code == 422

    consumption = client.post(
        f"/inventory/{variant_data['id']}/staff-consumption",
        json={"quantity": 10, "reason": "Staff lunch"},
        headers=auth_headers(cashier_token),
    )
    assert consumption.status_code == 201, consumption.text
    assert consumption.json()["movement_type"] == MovementType.STAFF_CONSUMPTION.value
    assert consumption.json()["quantity"] == -10
    assert Decimal(str(consumption.json()["unit_cost_at_time"])) == Decimal("0.12")

    expense = client.post(
        "/expenses",
        json={"category": "Transport", "amount": 5},
        headers=auth_headers(cashier_token),
    )
    assert expense.status_code == 201, expense.text

    stock = db.get(Variant, variant_data["id"])
    assert stock.quantity == 490
    movement = db.get(StockMovement, consumption.json()["id"])
    assert movement is not None

    report = client.get(
        f"/reports/summary?start_date={date.today()}&end_date={date.today()}",
        headers=auth_headers(admin_token),
    )
    assert report.status_code == 200, report.text
    assert report.json()["expense_total"] == 5.0
    assert report.json()["staff_consumption_total"] == 1.2
    assert report.json()["net_sales"] == -5.0
    assert report.json()["transaction_count"] == 0
    assert report.json()["daily_breakdown"][0]["staff_consumption_total"] == 1.2

    closed = client.post(
        "/cash-sessions/close",
        json={"closing_cash": 95},
        headers=auth_headers(cashier_token),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["expected_cash"] == 95.0


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