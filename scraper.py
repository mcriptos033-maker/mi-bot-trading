import re
import logging
from datetime import datetime, date
from typing import Optional

import pytz
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FXSTREET_URL = (
    "https://calendar-api.fxstreet.com/en/api/v1/eventDates"
    "/{from_date}/{to_date}?volatility=HIGH"
)
INVESTING_URL = (
    "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
)

_HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# FX Street
# ---------------------------------------------------------------------------

def get_fxstreet_events(target_date: date) -> list[dict]:
    from_dt = f"{target_date.isoformat()}T00:00:00Z"
    to_dt = f"{target_date.isoformat()}T23:59:59Z"
    url = FXSTREET_URL.format(from_date=from_dt, to_date=to_dt)

    headers = {
        **_HEADERS_BASE,
        "Accept": "application/json",
        "Origin": "https://www.fxstreet.com",
        "Referer": "https://www.fxstreet.com/economic-calendar",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("FX Street request failed: %s", exc)
        return []

    events = []
    for item in data:
        if item.get("volatility", "").upper() != "HIGH":
            continue

        time_str = item.get("dateUtc") or item.get("date") or ""
        time_utc = _parse_iso(time_str)
        if time_utc is None:
            continue

        events.append({
            "title": item.get("name") or item.get("title") or "",
            "currency": item.get("currencyCode") or item.get("country") or "",
            "time_utc": time_utc,
            "actual": _blank(item.get("actual")),
            "forecast": _blank(item.get("consensus") or item.get("forecast")),
            "previous": _blank(item.get("previous")),
            "source": "FX Street",
        })

    return events


# ---------------------------------------------------------------------------
# Investing.com
# ---------------------------------------------------------------------------

def get_investing_events(target_date: date) -> list[dict]:
    date_str = target_date.isoformat()

    session = requests.Session()
    session.headers.update(_HEADERS_BASE)

    # Fetch cookies first
    try:
        session.get(
            "https://www.investing.com/economic-calendar/",
            timeout=15,
        )
    except Exception as exc:
        logger.warning("Investing.com cookie fetch failed: %s", exc)

    post_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Referer": "https://www.investing.com/economic-calendar/",
        "Origin": "https://www.investing.com",
    }

    # importance[]: 3 = high impact only
    payload = {
        "importance[]": "3",
        "dateFrom": date_str,
        "dateTo": date_str,
        "submitFilters": "1",
        "limit_from": "0",
    }

    try:
        resp = session.post(
            INVESTING_URL, headers=post_headers, data=payload, timeout=20
        )
        resp.raise_for_status()
        html = resp.json().get("data", "")
    except Exception as exc:
        logger.error("Investing.com request failed: %s", exc)
        return []

    soup = BeautifulSoup(html, "lxml")
    events = []
    est = pytz.timezone("America/New_York")

    for row in soup.find_all("tr", class_="js-event-item"):
        try:
            time_cell = row.find("td", class_="time")
            time_raw = time_cell.get_text(strip=True) if time_cell else ""

            flag_cell = row.find("td", class_="flagCur")
            currency = flag_cell.get_text(strip=True) if flag_cell else ""

            event_cell = row.find("td", class_="event")
            title = event_cell.get_text(strip=True) if event_cell else ""

            actual_cell = row.find("td", id=re.compile(r"eventActual"))
            forecast_cell = row.find("td", id=re.compile(r"eventForecast"))
            previous_cell = row.find("td", id=re.compile(r"eventPrevious"))

            actual = _blank(_text(actual_cell))
            forecast = _blank(_text(forecast_cell))
            previous = _blank(_text(previous_cell))

            if time_raw and time_raw not in ("", "All Day", "Tentative"):
                try:
                    naive = datetime.strptime(f"{date_str} {time_raw}", "%Y-%m-%d %H:%M")
                    time_utc = est.localize(naive).astimezone(pytz.utc)
                except ValueError:
                    time_utc = None
            else:
                time_utc = None

            if title and currency:
                events.append({
                    "title": title,
                    "currency": currency,
                    "time_utc": time_utc,
                    "actual": actual,
                    "forecast": forecast,
                    "previous": previous,
                    "source": "Investing.com",
                })
        except Exception as exc:
            logger.debug("Row parse error: %s", exc)

    return events


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def get_high_impact_events(target_date: date) -> list[dict]:
    """Return merged, deduplicated, time-sorted high-impact events."""
    fx_events = get_fxstreet_events(target_date)
    inv_events = get_investing_events(target_date)

    seen: set[str] = {_dedup_key(e) for e in fx_events}
    merged = list(fx_events)

    for event in inv_events:
        k = _dedup_key(event)
        if k not in seen:
            merged.append(event)
            seen.add(k)

    merged.sort(
        key=lambda e: e["time_utc"]
        if e["time_utc"]
        else datetime.max.replace(tzinfo=pytz.utc)
    )
    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def _blank(val: Optional[str]) -> Optional[str]:
    if not val or val in ("-", "—", ""):
        return None
    return val


def _dedup_key(event: dict) -> str:
    title = re.sub(r"\s+", " ", event.get("title") or "").strip().lower()
    return title[:40]
