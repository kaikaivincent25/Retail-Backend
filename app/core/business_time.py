from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

BUSINESS_TIMEZONE = ZoneInfo(settings.BUSINESS_TIMEZONE)


def business_today(now: datetime | None = None) -> date:
    return (now or datetime.now(BUSINESS_TIMEZONE)).astimezone(BUSINESS_TIMEZONE).date()


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BUSINESS_TIMEZONE)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=BUSINESS_TIMEZONE)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
