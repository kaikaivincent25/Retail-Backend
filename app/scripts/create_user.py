import argparse
import getpass

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


def main():
    parser = argparse.ArgumentParser(description="Create a user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--role", choices=[r.value for r in UserRole], required=True)
    parser.add_argument("--shop-id", type=int, default=1)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    if len(password) < 6:
        raise SystemExit("Password must be at least 6 characters")

    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == args.username)):
            raise SystemExit(f"Username '{args.username}' already exists")

        user = User(
            shop_id=args.shop_id,
            full_name=args.full_name,
            username=args.username,
            password_hash=hash_password(password),
            role=UserRole(args.role),
        )
        db.add(user)
        db.commit()
        print(f"Created {user.role.value} '{user.username}' (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()