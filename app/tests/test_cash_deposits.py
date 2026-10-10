from decimal import Decimal

from tests.conftest import auth_headers


def test_partial_and_full_deposits_reduce_cash_carried_to_next_session(
    client, cashier_token
):
    opened = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )
    assert opened.status_code == 201, opened.text
    closed = client.post(
        "/cash-sessions/close",
        json={"closing_cash": 100},
        headers=auth_headers(cashier_token),
    )
    assert closed.status_code == 200, closed.text

    partial_deposit = client.post(
        "/cash-sessions/deposits",
        json={"amount": 35, "frequency": "daily"},
        headers=auth_headers(cashier_token),
    )
    assert partial_deposit.status_code == 201, partial_deposit.text
    assert partial_deposit.json()["amount"] == 35
    assert partial_deposit.json()["frequency"] == "daily"

    summary = client.get(
        "/cash-sessions/deposits", headers=auth_headers(cashier_token)
    )
    assert summary.status_code == 200
    assert summary.json()["available_cash"] == 65

    next_session = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )
    assert next_session.status_code == 201, next_session.text
    assert next_session.json()["opening_cash"] == 65
    next_close = client.post(
        "/cash-sessions/close",
        json={"closing_cash": 65},
        headers=auth_headers(cashier_token),
    )
    assert next_close.status_code == 200, next_close.text

    full_deposit = client.post(
        "/cash-sessions/deposits",
        json={"amount": 65, "frequency": "weekly"},
        headers=auth_headers(cashier_token),
    )
    assert full_deposit.status_code == 201, full_deposit.text
    assert full_deposit.json()["frequency"] == "weekly"

    summary = client.get(
        "/cash-sessions/deposits", headers=auth_headers(cashier_token)
    )
    assert summary.status_code == 200
    assert summary.json()["available_cash"] == 0
    assert len(summary.json()["deposits"]) == 2

    final_session = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )
    assert final_session.status_code == 201, final_session.text
    assert Decimal(str(final_session.json()["opening_cash"])) == Decimal("0.00")


def test_deposits_require_closed_session_and_cannot_exceed_available_cash(
    client, cashier_token
):
    no_session_deposit = client.post(
        "/cash-sessions/deposits",
        json={"amount": 1, "frequency": "daily"},
        headers=auth_headers(cashier_token),
    )
    assert no_session_deposit.status_code == 422
    assert "no closed cash session" in no_session_deposit.json()["detail"].lower()

    opened = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )
    assert opened.status_code == 201, opened.text
    close = client.post(
        "/cash-sessions/close",
        json={"closing_cash": 50},
        headers=auth_headers(cashier_token),
    )
    assert close.status_code == 200, close.text

    open_again = client.post(
        "/cash-sessions/open", json={}, headers=auth_headers(cashier_token)
    )
    assert open_again.status_code == 201, open_again.text
    blocked_deposit = client.post(
        "/cash-sessions/deposits",
        json={"amount": 1, "frequency": "daily"},
        headers=auth_headers(cashier_token),
    )
    assert blocked_deposit.status_code == 422
    assert "close the cash session" in blocked_deposit.json()["detail"].lower()

    client.post(
        "/cash-sessions/close",
        json={"closing_cash": 50},
        headers=auth_headers(cashier_token),
    )
    excess_deposit = client.post(
        "/cash-sessions/deposits",
        json={"amount": 50.01, "frequency": "weekly"},
        headers=auth_headers(cashier_token),
    )
    assert excess_deposit.status_code == 422
    assert "cannot exceed" in excess_deposit.json()["detail"].lower()
