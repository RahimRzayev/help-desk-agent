import pytest

from citywheels.tools import get_booking, run_tool, search_policies


# ---------------------------------------------------------------- get_booking

def test_get_booking_returns_the_booking():
    r = get_booking("CW-1002")
    assert r["found"] is True
    assert r["booking"]["bike_type"] == "e-bike"
    assert r["booking"]["bikes"] == 2


@pytest.mark.parametrize("raw", ["cw-1002", "CW1002", "CW 1002", " 1002 "])
def test_get_booking_accepts_common_spellings(raw):
    assert get_booking(raw)["booking"]["id"] == "CW-1002"


@pytest.mark.parametrize("raw", ["CW-9999", "XY-1002", "", "'; DROP TABLE", "1002abc"])
def test_get_booking_unknown_or_malformed_is_not_found(raw):
    r = get_booking(raw)
    assert r["found"] is False
    assert "No booking" in r["message"]


# ---------------------------------------------------------------- search_policies

def _sections(query):
    return [r["section"] for r in search_policies(query)["results"]]


def test_search_finds_opening_hours():
    assert _sections("opening hours on Saturday")[0] == "Frequently asked questions > When are you open?"


def test_search_finds_bike_prices():
    assert _sections("e-bike price per day")[0] == "Prices > Bike rental"


def test_search_finds_cancellation_rules():
    assert _sections("cancellation refund")[0] == "Cancellations and refunds > Cancelling a booking"


def test_search_finds_age_limits():
    assert "Frequently asked questions > Are there age limits?" in _sections("age limit for electric bikes")


def test_search_returns_at_most_top_k():
    assert len(search_policies("bike", top_k=2)["results"]) <= 2


def test_search_off_topic_returns_nothing():
    r = search_policies("capital of Australia")
    assert r["results"] == []
    assert "note" in r


def test_search_results_include_source_and_text():
    first = search_policies("helmet")["results"][0]
    assert first["source"] == "faq.md"
    assert "required for riders under 16" in first["text"]


# ---------------------------------------------------------------- run_tool

def test_run_tool_dispatches_by_name():
    assert run_tool("get_booking", {"booking_id": "CW-1001"})["found"] is True


def test_run_tool_unknown_tool_is_an_error_not_a_crash():
    assert "error" in run_tool("delete_everything", {})


def test_run_tool_bad_arguments_is_an_error_not_a_crash():
    assert "error" in run_tool("get_booking", {"wrong_name": "CW-1001"})
