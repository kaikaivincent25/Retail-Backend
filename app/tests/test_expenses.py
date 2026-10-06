from datetime import date
from decimal import Decimal

from app.models.cash_session import CashSession, SessionStatus
from app.models.user import UserRole
from tests.conftest import _make_user, _login, auth_headers


def test_expenses_are_scoped_and_subtracted_from_daily_sales(
    client, db, admin_token, cashier_token, cashier_user, shop
):
    session = CashSession(
        shop_id=shop.id,
        user_id=cashier_user.id,
        opening_cash=Decimal("100.00"),
        status=SessionStatus.OPEN,
    )
    second_cashier = _make_user(db, shop, "cashier2", UserRole.CASHIER)
    db.add_all([session, second_cashier])
    db.commit()
    db.refresh(session)
    db.refresh(second_cashier)

    first_expense = client.post(
        "/expenses",
        json={"category": "Meals", "description": "Lunch", "amount": 100},
        headers=auth_headers(cashier_token),
    )
    assert first_expense.status_code == 201, first_expense.text
    assert first_expense.json()["user_name"] == cashier_user.full_name

    second_cashier_token = _login(client, second_cashier.username)
    second_expense = client.post(
        "/expenses",
        json={"category": "Transport", "amount": 25},
        headers=auth_headers(second_cashier_token),
    )
    assert second_expense.status_code == 201, second_expense.text

    cashier_expenses = client.get("/expenses", headers=auth_headers(cashier_token))
    assert cashier_expenses.status_code == 200
    assert len(cashier_expenses.json()) == 1

    admin_expenses = client.get("/expenses", headers=auth_headers(admin_token))
    assert admin_expenses.status_code == 200
    assert {item["user_name"] for item in admin_expenses.json()} == {
        cashier_user.full_name,
        second_cashier.full_name,
    }

    dashboard = client.get(
        "/dashboard/cashier-summary", headers=auth_headers(cashier_token)
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["expense_total"] == 125.0
    assert dashboard.json()["net_sales"] == -125.0

    report = client.get(
        f"/reports/summary?start_date={date.today()}&end_date={date.today()}",
        headers=auth_headers(admin_token),
    )
    assert report.status_code == 200, report.text
    assert report.json()["expense_total"] == 125.0
    assert report.json()["net_sales"] == -125.0
    assert report.json()["daily_breakdown"][0]["net_sales"] == -125.0


def test_expense_requires_an_open_cash_session(client, cashier_token):
    response = client.post(
        "/expenses",
        json={"category": "Meals", "amount": 100},
        headers=auth_headers(cashier_token),
    )

    assert response.status_code == 422
    assert "open cash session" in response.json()["detail"].lower()
