"""One test per cancellation rule in data/policies/cancellations.md.

"Now" is fixed at 2026-06-10 09:00 +02:00 (see data README).
"""

import pytest

from citywheels.tools import calculate_refund


def test_48_hours_or_more_refunds_full_rental_plus_deposit():
    # CW-1001 starts 2026-06-13 10:00, 73 hours away.
    r = calculate_refund("CW-1001")
    assert r["can_cancel"] is True
    assert r["rental_refund_percent"] == 100
    assert r["rental_refund_eur"] == 40.0
    assert r["deposit_refund_eur"] == 50.0
    assert r["total_refund_eur"] == 90.0


def test_exactly_48_hours_counts_as_48_or_more():
    # CW-1007 starts 2026-06-12 09:00, exactly 48 hours away.
    r = calculate_refund("CW-1007")
    assert r["hours_before_start"] == 48.0
    assert r["rental_refund_percent"] == 100
    assert r["total_refund_eur"] == 36.0 + 150.0


def test_one_second_under_48_hours_drops_to_50_percent():
    r = calculate_refund("CW-1007", cancel_at="2026-06-10T09:00:01+02:00")
    assert r["rental_refund_percent"] == 50
    assert r["total_refund_eur"] == 18.0 + 150.0


def test_between_24_and_48_hours_refunds_half_the_rental():
    # CW-1002 starts 2026-06-11 18:00, 33 hours away.
    r = calculate_refund("CW-1002")
    assert r["rental_refund_percent"] == 50
    assert r["rental_refund_eur"] == 40.0
    assert r["deposit_refund_eur"] == 300.0
    assert r["total_refund_eur"] == 340.0


def test_exactly_24_hours_counts_as_24_or_more():
    # CW-1010 starts 2026-06-11 09:00, exactly 24 hours away.
    r = calculate_refund("CW-1010")
    assert r["hours_before_start"] == 24.0
    assert r["rental_refund_percent"] == 50
    assert r["total_refund_eur"] == 20.0 + 150.0


def test_less_than_24_hours_refunds_no_rental_but_still_the_deposit():
    # CW-1003 starts 2026-06-10 15:00, 6 hours away.
    r = calculate_refund("CW-1003")
    assert r["can_cancel"] is True
    assert r["rental_refund_percent"] == 0
    assert r["rental_refund_eur"] == 0.0
    assert r["deposit_refund_eur"] == 50.0
    assert r["total_refund_eur"] == 50.0


@pytest.mark.parametrize("booking_id", ["CW-1001", "CW-1002", "CW-1003", "CW-1004"])
def test_booking_fee_is_never_refunded(booking_id):
    r = calculate_refund(booking_id)
    assert r["booking_fee_not_refunded_eur"] == 2.0
    assert r["total_refund_eur"] == r["rental_refund_eur"] + r["deposit_refund_eur"]


@pytest.mark.parametrize(
    "booking_id, status",
    [("CW-1005", "cancelled"), ("CW-1006", "completed"), ("CW-1008", "in_progress")],
)
def test_only_confirmed_bookings_can_be_cancelled(booking_id, status):
    r = calculate_refund(booking_id)
    assert r["status"] == status
    assert r["can_cancel"] is False
    assert r["total_refund_eur"] == 0.0


def test_card_payment_is_refunded_to_the_card():
    r = calculate_refund("CW-1001")
    assert "same card" in r["refund_method"]


def test_voucher_payment_is_refunded_as_a_voucher():
    # CW-1004: 240 hours away, paid with a voucher, includes a child seat.
    r = calculate_refund("CW-1004")
    assert r["total_refund_eur"] == 23.0 + 50.0
    assert "voucher" in r["refund_method"]
    assert "never as money" in r["refund_method"]


def test_long_rental_uses_the_discounted_price_it_was_booked_at():
    # CW-1009: 7-day rental, already discounted to 119 EUR.
    r = calculate_refund("CW-1009")
    assert r["total_refund_eur"] == 119.0 + 50.0


def test_cancelling_later_can_change_the_rule():
    # "What if I cancel CW-1002 tomorrow instead?" -> 9 hours before start.
    r = calculate_refund("CW-1002", cancel_at="2026-06-11T09:00:00+02:00")
    assert r["rental_refund_percent"] == 0
    assert r["total_refund_eur"] == 300.0


def test_cancel_time_without_timezone_is_read_as_shop_time():
    r = calculate_refund("CW-1002", cancel_at="2026-06-11T09:00:00")
    assert r["hours_before_start"] == 9.0


def test_cancelling_after_the_start_is_not_possible():
    r = calculate_refund("CW-1003", cancel_at="2026-06-10T16:00:00+02:00")
    assert r["can_cancel"] is False
    assert r["total_refund_eur"] == 0.0


def test_cancel_time_in_the_past_is_an_error():
    r = calculate_refund("CW-1001", cancel_at="2026-06-01T09:00:00+02:00")
    assert "error" in r


def test_invalid_cancel_time_is_an_error_not_a_crash():
    r = calculate_refund("CW-1001", cancel_at="next tuesday-ish")
    assert "error" in r


def test_unknown_booking_is_not_found():
    r = calculate_refund("CW-9999")
    assert r["found"] is False
