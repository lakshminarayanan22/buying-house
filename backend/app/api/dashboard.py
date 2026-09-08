"""The three screens that get opened daily, plus the pipeline behind them."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.db import get_db
from app.models import User
from app.services import deals as svc

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    shipping_days: int = Query(7, ge=1, le=90),
    quiet_days: int = Query(14, ge=1, le=365),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "shipping": svc.shipping_soon(db, within_days=shipping_days),
        "commission": svc.commission_owed(db),
        "quiet": svc.gone_quiet(db, silent_for_days=quiet_days),
        "milestones": svc.open_milestones(db),
        "pipeline": svc.pipeline(db),
    }
