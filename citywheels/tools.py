"""The agent's tools. Plain Python functions that return JSON-serializable dicts.

All facts and amounts come from here, never from the model.
"""

import json
import math
import re
from datetime import datetime
from functools import lru_cache

from citywheels.config import BOOKINGS_FILE, NOW, POLICIES_DIR

# ---------------------------------------------------------------- search_policies

STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "can", "do", "does", "for", "how", "i",
    "if", "in", "is", "it", "me", "my", "of", "on", "or", "the", "there", "this",
    "that", "to", "what", "when", "where", "will", "with", "would", "you", "your",
    "much", "many", "get", "we", "our",
}


def _stem(word: str) -> str:
    """Very small suffix stripper so 'opening' matches 'open', 'cancellations' matches 'cancel'."""
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        word = word[:-1]
    for suffix in ("ation", "ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            # 'cancell' -> 'cancel', 'stopp' -> 'stop'
            if len(word) >= 5 and word[-1] == word[-2] and word[-1] not in "aeiou":
                word = word[:-1]
            break
    return word


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]


@lru_cache(maxsize=1)
def _load_sections() -> list[dict]:
    """Split every policy file into sections at its '## ' headings."""
    sections = []
    for path in sorted(POLICIES_DIR.glob("*.md")):
        title = ""
        heading, lines = None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if heading:
                    sections.append(_make_section(path.name, title, heading, lines))
                heading, lines = line[3:].strip(), []
            elif heading:
                lines.append(line)
        if heading:
            sections.append(_make_section(path.name, title, heading, lines))
    return sections


def _make_section(source: str, title: str, heading: str, lines: list[str]) -> dict:
    text = "\n".join(lines).strip()
    return {
        "source": source,
        "title": title,
        "heading": heading,
        "text": text,
        "_heading_tokens": set(_tokenize(heading)),
        "_tokens": set(_tokenize(f"{title} {heading} {text}")),
    }


def search_policies(query: str, top_k: int = 3) -> dict:
    """Return the policy sections that share the most (rare) words with the query."""
    sections = _load_sections()
    query_terms = set(_tokenize(query))
    if not query_terms:
        return {"query": query, "results": [], "note": "The query has no searchable words."}

    # Words that appear in few sections count more than words that appear everywhere.
    n = len(sections)
    idf = {t: math.log(1 + n / (1 + sum(t in s["_tokens"] for s in sections))) for t in query_terms}

    scored = []
    for s in sections:
        score = sum(idf[t] for t in query_terms if t in s["_tokens"])
        score += sum(idf[t] for t in query_terms if t in s["_heading_tokens"])
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    results = [
        {"source": s["source"], "section": f"{s['title']} > {s['heading']}", "text": s["text"]}
        for _, s in scored[:top_k]
    ]
    if not results:
        return {"query": query, "results": [], "note": "No policy section matches this query."}
    return {"query": query, "results": results}


# ---------------------------------------------------------------- get_booking

def _load_bookings() -> dict[str, dict]:
    with open(BOOKINGS_FILE, encoding="utf-8") as f:
        return {b["id"]: b for b in json.load(f)}


def _normalize_booking_id(booking_id: str) -> str | None:
    """Accept 'CW-1002', 'cw1002', 'CW 1002' or '1002'. Return None for anything else."""
    match = re.fullmatch(r"\s*(?:cw[-\s]?)?(\d+)\s*", str(booking_id), flags=re.IGNORECASE)
    return f"CW-{match.group(1)}" if match else None


def _not_found(booking_id: str) -> dict:
    return {
        "found": False,
        "booking_id": booking_id,
        "message": f"No booking with number '{booking_id}' exists. Booking numbers look like CW-1001.",
    }


def get_booking(booking_id: str) -> dict:
    normalized = _normalize_booking_id(booking_id)
    booking = _load_bookings().get(normalized) if normalized else None
    if booking is None:
        return _not_found(booking_id)
    return {"found": True, "booking": booking}


# ---------------------------------------------------------------- calculate_refund

def _refund_percent(hours_before_start: float) -> tuple[int, str]:
    if hours_before_start >= 48:
        return 100, "Cancelled 48 hours or more before the start: 100% of the rental price."
    if hours_before_start >= 24:
        return 50, "Cancelled less than 48 but at least 24 hours before the start: 50% of the rental price."
    return 0, "Cancelled less than 24 hours before the start: 0% of the rental price."


def _refund_method(paid_with: str) -> str:
    if paid_with == "voucher":
        return "Refunded as a new voucher of the same value, never as money. The deposit is refunded the same way it was paid."
    return "Refunded to the same card within 5 working days."


def calculate_refund(booking_id: str, cancel_at: str | None = None, now: datetime = NOW) -> dict:
    """Refund for cancelling a booking at `cancel_at` (ISO 8601). Defaults to the current time."""
    found = get_booking(booking_id)
    if not found["found"]:
        return found
    booking = found["booking"]

    if cancel_at is None:
        when = now
    else:
        try:
            when = datetime.fromisoformat(cancel_at)
        except (TypeError, ValueError):
            return {"error": f"cancel_at '{cancel_at}' is not a valid ISO 8601 date and time."}
        if when.tzinfo is None:
            when = when.replace(tzinfo=now.tzinfo)
        if when < now:
            return {"error": f"cancel_at {when.isoformat()} is in the past. The current time is {now.isoformat()}."}

    result = {
        "found": True,
        "booking_id": booking["id"],
        "status": booking["status"],
        "cancel_at": when.isoformat(),
        "start": booking["start"],
        "paid_with": booking["paid_with"],
    }

    start = datetime.fromisoformat(booking["start"])
    if booking["status"] != "confirmed":
        reason = f"Bookings with the status '{booking['status']}' cannot be cancelled, and nothing is refunded."
    elif when >= start:
        reason = "The rental has already started at this time, so the booking cannot be cancelled."
    else:
        reason = None
    if reason:
        return {**result, "can_cancel": False, "reason": reason, "total_refund_eur": 0.0}

    hours = (start - when).total_seconds() / 3600
    percent, rule = _refund_percent(hours)
    rental_refund = round(booking["rental_price_eur"] * percent / 100, 2)
    deposit_refund = booking["deposit_eur"]  # always refunded in full on cancellation
    return {
        **result,
        "can_cancel": True,
        "hours_before_start": round(hours, 2),
        "rule": rule,
        "rental_price_eur": booking["rental_price_eur"],
        "rental_refund_percent": percent,
        "rental_refund_eur": rental_refund,
        "deposit_refund_eur": deposit_refund,
        "booking_fee_not_refunded_eur": booking["booking_fee_eur"],
        "total_refund_eur": round(rental_refund + deposit_refund, 2),
        "refund_method": _refund_method(booking["paid_with"]),
    }


# ---------------------------------------------------------------- quote_price

# Mirrors data/policies/prices.md. tests/test_quote.py checks it reproduces every booking's price.
HOURLY_PRICE_EUR = {"city": 4, "e-bike": 9, "kids": 2}
DAY_PRICE_EUR = {"city": 20, "e-bike": 40, "kids": 10}
DEPOSIT_PER_BIKE_EUR = {"city": 50, "e-bike": 150, "kids": 30}
ADD_ON_PRICE_PER_DAY_EUR = {"child_seat": 3}
ONLINE_BOOKING_FEE_EUR = 2
LONG_RENTAL_HOURS = 7 * 24
LONG_RENTAL_DISCOUNT = 0.15
LATE_RETURN_MULTIPLIER = 1.5


def quote_price(
    bike_type: str, bikes: int, hours: float, add_ons: list[str] | None = None, booked_online: bool = True
) -> dict:
    """Price of a new rental, following prices.md.

    Assumptions where prices.md is not explicit: a rental over 6 hours is charged per started
    day, add-ons are charged per started day, and the 7-day discount applies to bikes only.
    """
    add_ons = list(add_ons or [])
    if bike_type not in HOURLY_PRICE_EUR:
        return {"error": f"Unknown bike type '{bike_type}'. Bike types are: city, e-bike, kids."}
    if not isinstance(bikes, int) or bikes < 1:
        return {"error": "bikes must be a whole number of at least 1."}
    if not isinstance(hours, (int, float)) or hours <= 0:
        return {"error": "hours must be a number greater than 0."}
    unknown = [a for a in add_ons if a not in ADD_ON_PRICE_PER_DAY_EUR]
    if unknown:
        return {"error": f"Unknown add-ons {unknown}. Paid add-ons: child_seat. Extra lock and helmet are free."}

    started_days = math.ceil(hours / 24)
    if hours <= 6:
        started_hours = math.ceil(hours)
        bike_rental = started_hours * HOURLY_PRICE_EUR[bike_type] * bikes
        charged_as = f"{started_hours} started hour(s) x {HOURLY_PRICE_EUR[bike_type]} EUR x {bikes} bike(s)"
    else:
        bike_rental = started_days * DAY_PRICE_EUR[bike_type] * bikes
        charged_as = f"{started_days} day(s) x {DAY_PRICE_EUR[bike_type]} EUR x {bikes} bike(s)"

    discount = round(bike_rental * LONG_RENTAL_DISCOUNT, 2) if hours >= LONG_RENTAL_HOURS else 0.0
    add_ons_cost = sum(ADD_ON_PRICE_PER_DAY_EUR[a] * started_days for a in add_ons)
    rental_price = round(bike_rental - discount + add_ons_cost, 2)
    booking_fee = float(ONLINE_BOOKING_FEE_EUR if booked_online else 0)
    deposit = float(DEPOSIT_PER_BIKE_EUR[bike_type] * bikes)
    return {
        "bike_type": bike_type,
        "bikes": bikes,
        "hours": hours,
        "add_ons": add_ons,
        "charged_as": charged_as,
        "bike_rental_eur": float(bike_rental),
        "long_rental_discount_eur": discount,
        "add_ons_eur": float(add_ons_cost),
        "rental_price_eur": rental_price,
        "booking_fee_eur": booking_fee,
        "deposit_eur": deposit,
        "total_to_pay_eur": round(rental_price + booking_fee + deposit, 2),
        "deposit_note": "The deposit is returned in full when the bikes come back on time and without damage.",
    }


# ---------------------------------------------------------------- calculate_late_fee

def calculate_late_fee(bike_type: str, bikes: int, hours_late: float) -> dict:
    """Late return fee: 1.5 x the hourly price for every started hour of delay, per bike."""
    if bike_type not in HOURLY_PRICE_EUR:
        return {"error": f"Unknown bike type '{bike_type}'. Bike types are: city, e-bike, kids."}
    if not isinstance(bikes, int) or bikes < 1:
        return {"error": "bikes must be a whole number of at least 1."}
    if not isinstance(hours_late, (int, float)) or hours_late <= 0:
        return {"error": "hours_late must be a number greater than 0."}

    started_hours = math.ceil(hours_late)
    fee_per_hour = HOURLY_PRICE_EUR[bike_type] * LATE_RETURN_MULTIPLIER
    return {
        "bike_type": bike_type,
        "bikes": bikes,
        "hours_late": hours_late,
        "started_hours_charged": started_hours,
        "fee_per_hour_per_bike_eur": fee_per_hour,
        "late_fee_eur": round(fee_per_hour * started_hours * bikes, 2),
        "note": "The late fee is taken from the deposit.",
    }


# ---------------------------------------------------------------- dispatch

TOOL_FUNCTIONS = {
    "search_policies": search_policies,
    "get_booking": get_booking,
    "calculate_refund": calculate_refund,
    "quote_price": quote_price,
    "calculate_late_fee": calculate_late_fee,
}

# Tool definitions sent to the model. The descriptions say *when* to call each tool.
TOOL_SCHEMAS = [
    {
        "name": "search_policies",
        "description": (
            "Search the CityWheels policy documents: prices, add-ons, deposits, late return fees, "
            "cancellations and refunds, and the FAQ (opening hours, location, what you need to rent, "
            "payment, age limits, helmets, dogs, trains and travel abroad, accidents, theft). "
            "Call this before answering ANY question about the shop's rules, prices, hours or services. "
            "Returns the most relevant sections. An empty result means the documents do not cover it."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords for what the customer wants to know, e.g. 'opening hours Saturday'.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_booking",
        "description": (
            "Look up one booking by its number, e.g. CW-1001. Call this whenever the customer asks about "
            "a specific booking (dates, bikes, status, price, payment). Returns found=false when no "
            "booking has that number."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "The booking number, e.g. CW-1001."},
            },
            "required": ["booking_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_refund",
        "description": (
            "Calculate exactly how much the customer gets back if they cancel a booking, following the "
            "cancellation rules. Call this for every question about cancelling a booking or about refund "
            "amounts; never work out a refund yourself. Set cancel_at when the customer asks about "
            "cancelling at another time ('tomorrow', 'on Friday')."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string", "description": "The booking number, e.g. CW-1002."},
                "cancel_at": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": (
                        "When the customer would cancel, ISO 8601 with offset, e.g. "
                        "2026-06-11T09:00:00+02:00. null means now."
                    ),
                },
            },
            "required": ["booking_id", "cancel_at"],
            "additionalProperties": False,
        },
    },
    {
        "name": "quote_price",
        "description": (
            "Calculate what a new rental costs: rental price, add-ons, long-rental discount, booking fee "
            "and deposit. Call this whenever the customer asks what renting would cost for some duration "
            "or number of bikes; never multiply prices yourself."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "bike_type": {"type": "string", "enum": ["city", "e-bike", "kids"]},
                "bikes": {"type": "integer", "description": "Number of bikes."},
                "hours": {"type": "number", "description": "Rental length in hours. 1 day = 24, 1 week = 168."},
                "add_ons": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["child_seat"]},
                    "description": "One entry per child seat. Empty list if none.",
                },
                "booked_online": {
                    "type": "boolean",
                    "description": "true if booked online (booking fee applies), false if booked in the shop. Use true if unknown.",
                },
            },
            "required": ["bike_type", "bikes", "hours", "add_ons", "booked_online"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_late_fee",
        "description": (
            "Calculate the fee for returning bikes after the end of the rental. Call this whenever the "
            "customer asks what a late return costs; never multiply prices yourself."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "bike_type": {"type": "string", "enum": ["city", "e-bike", "kids"]},
                "bikes": {"type": "integer", "description": "Number of bikes returned late."},
                "hours_late": {"type": "number", "description": "How many hours after the end of the rental."},
            },
            "required": ["bike_type", "bikes", "hours_late"],
            "additionalProperties": False,
        },
    },
]


def run_tool(name: str, arguments: dict) -> dict:
    """Run a tool by name. Never raises: errors come back as {'error': ...} for the model to read."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return func(**arguments)
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
