import pytest  # pyright: ignore[reportMissingImports]
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.shop import Shop
from app.models.user import User, UserRole

TEST_DATABASE_URL = "postgresql+psycopg://retail_user:change_me@localhost:5432/retail_test_db"

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
        Base.metadata.drop_all(bind=engine)  # full reset after every single test


@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def shop(db):
    s = Shop(name="Test Duka", currency="KES")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_user(db, shop, username, role, password="password123"):
    user = User(
        shop_id=shop.id, full_name=username.title(), username=username,
        password_hash=hash_password(password), role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_user(db, shop):
    return _make_user(db, shop, "admin", UserRole.ADMIN)


@pytest.fixture()
def cashier_user(db, shop):
    return _make_user(db, shop, "cashier1", UserRole.CASHIER)


def _login(client, username, password="password123"):
    resp = client.post("/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def admin_token(client, admin_user):
    return _login(client, admin_user.username)


@pytest.fixture()
def cashier_token(client, cashier_user):
    return _login(client, cashier_user.username)


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}