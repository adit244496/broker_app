"""
Management commands:
  python -m app.cli init-db
  python -m app.cli create-admin --email admin@ambujaneotia.com --name "Portal Admin"
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import func, select

from app.db import Base, SessionLocal, add_missing_columns, engine
from app.models import AdminUser
from app.security import hash_password

MIN_PASSWORD = 8


def init_db() -> None:
    Base.metadata.create_all(engine)
    add_missing_columns()
    print("Tables created.")


def create_admin(email: str, name: str) -> None:
    # ADMIN_PASSWORD lets this run non-interactively (e.g. a deploy script); otherwise prompt.
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD:
        sys.exit(f"Password must be at least {MIN_PASSWORD} characters.")
    if not os.environ.get("ADMIN_PASSWORD") and password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords don't match.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        existing = db.scalar(select(AdminUser).where(func.lower(AdminUser.email) == email.lower()))
        if existing:
            existing.password_hash = hash_password(password)
            existing.name = name
            existing.is_active = True
            existing.failed_logins = 0
            existing.locked_until = None
            print(f"Updated admin {email}.")
        else:
            db.add(AdminUser(email=email.lower(), name=name, password_hash=hash_password(password)))
            print(f"Created admin {email}.")
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create database tables")
    admin = sub.add_parser("create-admin", help="Create an admin, or reset an existing admin's password")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
    else:
        create_admin(args.email, args.name)


if __name__ == "__main__":
    main()
