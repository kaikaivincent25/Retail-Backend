"""Create the first RIS platform owner interactively.

Run once against the configured database:
    python -m app.scripts.create_platform_owner
"""
import getpass

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.platform import PlatformUser


def main() -> None:
    full_name = input("Platform owner name: ").strip()
    username = input("Platform owner username: ").strip()
    password = getpass.getpass("Platform owner password: ")
    confirmation = getpass.getpass("Repeat password: ")
    if not full_name or not username or len(password) < 12 or password != confirmation:
        raise SystemExit("Name, username, and a matching password of at least 12 characters are required.")

    with SessionLocal() as db:
        if db.scalar(select(PlatformUser).where(PlatformUser.username == username)):
            raise SystemExit("That platform username already exists.")
        db.add(PlatformUser(full_name=full_name, username=username, password_hash=hash_password(password)))
        db.commit()
    print("Platform owner created. Use /platform/login to sign in.")


if __name__ == "__main__":
    main()
