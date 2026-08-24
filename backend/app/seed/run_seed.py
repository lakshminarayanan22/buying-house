"""Entry point: `python -m app.seed.run_seed` loads master data and notification templates."""
import logging

from app.db import SessionLocal
from app.seed.master_data import seed_master_data
from app.seed.notification_templates import seed_notification_templates

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")


def main() -> None:
    db = SessionLocal()
    try:
        counts = seed_master_data(db)
        total = sum(counts.values())
        log.info("master data: %s values across %s domains", total, len(counts))
        for domain, count in sorted(counts.items()):
            log.info("  %-24s %s", domain, count)

        templates = seed_notification_templates(db)
        log.info("notification templates: %s", templates)
    finally:
        db.close()


if __name__ == "__main__":
    main()
