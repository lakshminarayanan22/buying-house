"""Create the first internal Super Admin.

Internal accounts are deliberately not creatable through any HTTP endpoint — the invite flow
refuses internal roles — so the first one has to come from the command line. Everyone else is
invited from inside the console.

    python -m app.seed.bootstrap_admin [email] [password]
"""
import logging
import secrets
import sys

from sqlalchemy import func, select

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import Role, UserStatus
from app.models import User

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("bootstrap")

DEFAULT_EMAIL = "admin@buyinghouse.co"


def main() -> None:
    email = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL).strip().lower()
    # A generated password beats a memorable default that survives into production.
    password = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(12)

    db = SessionLocal()
    try:
        existing = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if existing is not None:
            log.info("A user already exists for %s — nothing to do.", email)
            return

        db.add(
            User(
                org_id=None,
                role=Role.INTERNAL_SUPER_ADMIN,
                name="Super Admin",
                email=email,
                password_hash=hash_password(password),
                status=UserStatus.ACTIVE,
            )
        )
        db.commit()
        log.info("Created Super Admin\n  email:    %s\n  password: %s", email, password)
        log.info("Change this password after first sign-in.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
