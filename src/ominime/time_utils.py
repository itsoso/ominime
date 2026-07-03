"""Business-day time helpers for OmniMe."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import config


DEFAULT_DAY_TIMEZONE = "Asia/Shanghai"
DEFAULT_STORAGE_TIMEZONE = "America/New_York"


def _zoneinfo(name: str | None, fallback: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except ZoneInfoNotFoundError:
        return ZoneInfo(fallback)


def day_timezone() -> ZoneInfo:
    return _zoneinfo(
        getattr(config, "day_timezone", DEFAULT_DAY_TIMEZONE),
        DEFAULT_DAY_TIMEZONE,
    )


def storage_timezone() -> ZoneInfo:
    return _zoneinfo(
        getattr(config, "storage_timezone", DEFAULT_STORAGE_TIMEZONE),
        DEFAULT_STORAGE_TIMEZONE,
    )


def business_today() -> date:
    """Return today's date in the configured business-day timezone."""
    return datetime.now(day_timezone()).date()


def storage_now() -> datetime:
    """Return a naive timestamp in the configured storage timezone."""
    return datetime.now(storage_timezone()).replace(tzinfo=None)


def business_day_bounds_for_storage(target_date: date) -> tuple[datetime, datetime]:
    """Return naive storage-time bounds for a business date."""
    start = datetime.combine(target_date, time.min, tzinfo=day_timezone())
    end = start + timedelta(days=1)
    storage_tz = storage_timezone()
    return (
        start.astimezone(storage_tz).replace(tzinfo=None),
        end.astimezone(storage_tz).replace(tzinfo=None),
    )


def storage_timestamp_to_business_date(value: datetime) -> date:
    """Convert a stored timestamp to its business-day date."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=storage_timezone())
    return value.astimezone(day_timezone()).date()
