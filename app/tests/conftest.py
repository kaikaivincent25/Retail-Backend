import os

import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.shop import Shop
from app.models.user import User, UserRole

if settings.ENVIRONMENT.lower() != "test":
    raise RuntimeError("Set ENVIRONMENT=test before running pytest.")

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", settings.TEST_DATABASE_URL
).strip()
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "Set TEST_DATABASE_URL to a dedicated disposable PostgreSQL test database "
        "before running pytest."
    )
test_url = make_url(TEST_DATABASE_URL)
app_url = make_url(settings.DATABASE_URL)
if (
    test_url.host,
    test_url.port,
    test_url.database,
) == (
    app_url.host,
    app_url.port,
    app_url.database,
):
    raise RuntimeError("TEST_DATABASE_URL must not point to DATABASE_URL.")

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def shop(db):
    shop = Shop(name="Test Duka", currency="KES")
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


def _make_user(db, shop, username, role, password="test-password"):
    user = User(
        shop_id=shop.id,
        full_name=username.title(),
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_user(db, shop):
    return _make_user(db, shop, "admin", UserRole.ADMIN, "adminpass")


@pytest.fixture()
def cashier_user(db, shop):
    return _make_user(db, shop, "cashier1", UserRole.CASHIER, "cashierpass")


def _login(client, username, password="test-password"):
    response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def admin_token(client, admin_user):
    return _login(client, admin_user.username, "adminpass")


@pytest.fixture()
def cashier_token(client, cashier_user):
    return _login(client, cashier_user.username, "cashierpass")


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
