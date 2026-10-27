"""quote_price follows data/policies/prices.md."""

import json
from datetime import datetime

import pytest

from citywheels.config import BOOKINGS_FILE
from citywheels.tools import quote_price

BOOKINGS = json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("booking", BOOKINGS, ids=[b["id"] for b in BOOKINGS])
def test_quote_reproduces_every_booking_in_the_data(booking):
    hours = (datetime.fromisoformat(booking["end"]) - datetime.fromisoformat(booking["start"])).total_seconds() / 3600
    q = quote_price(
        booking["bike_type"], booking["bikes"], hours, booking["add_ons"], booked_online=booking["booking_fee_eur"] > 0
    )
    assert q["rental_price_eur"] == booking["rental_price_eur"]
    assert q["deposit_eur"] == booking["deposit_eur"]
    assert q["booking_fee_eur"] == booking["booking_fee_eur"]


def test_hourly_rental_charges_every_started_hour():
    assert quote_price("city", 1, 2.5)["rental_price_eur"] == 3 * 4


def test_six_hours_is_still_hourly():
    assert quote_price("city", 1, 6)["rental_price_eur"] == 6 * 4


def test_more_than_six_hours_is_the_day_price():
    # Literal reading of prices.md: 7 hours (20 EUR) is cheaper than 6 hours (24 EUR).
    assert quote_price("city", 1, 7)["rental_price_eur"] == 20


def test_multi_day_rental_charges_every_started_day():
    assert quote_price("e-bike", 1, 30)["rental_price_eur"] == 2 * 40


def test_seven_days_get_15_percent_off():
    q = quote_price("e-bike", 1, 7 * 24)
    assert q["long_rental_discount_eur"] == 42.0
    assert q["rental_price_eur"] == 7 * 40 - 42.0


def test_six_days_get_no_discount():
    assert quote_price("e-bike", 1, 6 * 24)["long_rental_discount_eur"] == 0.0


def test_child_seat_is_charged_per_started_day():
    assert quote_price("city", 1, 48, ["child_seat"])["add_ons_eur"] == 2 * 3


def test_deposit_and_booking_fee_are_added_to_the_total():
    q = quote_price("city", 2, 3)
    assert q["rental_price_eur"] == 24.0
    assert q["deposit_eur"] == 100.0
    assert q["booking_fee_eur"] == 2.0
    assert q["total_to_pay_eur"] == 126.0


def test_shop_booking_has_no_booking_fee():
    assert quote_price("city", 1, 3, booked_online=False)["booking_fee_eur"] == 0.0


@pytest.mark.parametrize(
    "args",
    [
        ("tandem", 1, 3),
        ("city", 0, 3),
        ("city", 1, 0),
        ("city", 1, -2),
        ("city", 1, "three"),
    ],
)
def test_bad_input_is_an_error_not_a_crash(args):
    assert "error" in quote_price(*args)


def test_unknown_add_on_is_an_error():
    assert "error" in quote_price("city", 1, 3, ["jetpack"])
