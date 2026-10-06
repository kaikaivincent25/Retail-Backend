from tests.conftest import auth_headers

from app.core.security import hash_password


def test_user_can_update_own_profile(client, admin_token):
    resp = client.patch(
        "/auth/me",
        json={"username": "newadmin", "full_name": "New Admin"},
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "newadmin"
    assert resp.json()["full_name"] == "New Admin"


def test_user_cannot_claim_another_users_username(client, admin_token):
    resp = client.patch(
        "/auth/me",
        json={"username": "cashier1"},
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Username 'cashier1' is already taken"


def test_changing_password_requires_correct_current_password(client, admin_token):
    resp = client.post(
        "/auth/change-password",
        json={"current_password": "incorrect", "new_password": "new-password"},
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Current password is incorrect"


def test_user_can_change_password_with_current_password(
    client, db, admin_user, admin_token
):
    admin_user.password_hash = hash_password("old-password")
    db.commit()

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "old-password", "new_password": "new-password"},
        headers=auth_headers(admin_token),
    )

    assert resp.status_code == 204
    assert client.post(
        "/auth/login", data={"username": "admin", "password": "new-password"}
    ).status_code == 200
    assert client.post(
        "/auth/login", data={"username": "admin", "password": "old-password"}
    ).status_code == 401
