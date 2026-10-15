"""UTC monthly period value object and resolver."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Period:
    key: str
    start: datetime
    end: datetime

    @property
    def is_current(self) -> bool:
        now = datetime.now(UTC)
        return self.start <= now < self.end


_MONTHS = {name.casefold(): number for number, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.casefold(): number for number, name in enumerate(calendar.month_abbr) if name})


def _period_for(year: int, month: int) -> Period:
    if not 1 <= month <= 12:
        raise ValueError("Month must be between 1 and 12")
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return Period(key=f"{year:04d}-{month:02d}", start=start, end=end)


def resolve_period(value: str, *, now: datetime | None = None) -> Period:
    """Resolve YYYY-MM, month names, and current/last month into UTC boundaries."""

    reference = (now or datetime.now(UTC)).astimezone(UTC)
    text = " ".join(value.strip().casefold().replace(",", " ").split())
    if not text:
        raise ValueError("Period cannot be empty")

    exact = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if exact:
        period = _period_for(int(exact.group(1)), int(exact.group(2)))
    elif text in {"current month", "this month"}:
        period = _period_for(reference.year, reference.month)
    elif text in {"last month", "previous month"}:
        year = reference.year if reference.month > 1 else reference.year - 1
        month = reference.month - 1 if reference.month > 1 else 12
        period = _period_for(year, month)
    else:
        named = re.fullmatch(r"([a-z]+)(?:\s+(\d{4}))?", text)
        if not named or named.group(1) not in _MONTHS:
            raise ValueError(
                "Unsupported period. Use YYYY-MM, a month name, 'this month', or 'last month'."
            )
        month = _MONTHS[named.group(1)]
        year = int(named.group(2)) if named.group(2) else reference.year
        if named.group(2) is None and month > reference.month:
            year -= 1
        period = _period_for(year, month)

    current_start = datetime(reference.year, reference.month, 1, tzinfo=UTC)
    if period.start > current_start:
        raise ValueError("Future periods are not supported")
    return period
