"""Tests for the evaluation graders, so a pass in eval/results.md means what it says."""

import json
from pathlib import Path

import pytest

from eval.checks import KNOWN_KEYS, contains_any, grade, mentions_amount, money_amounts

QUESTIONS = json.loads((Path(__file__).parent.parent / "eval" / "questions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("text", ["340", "€340", "340 EUR", "340.00 EUR", "EUR 340,00", "**€340.00**", "total: 340."])
def test_amount_is_found_in_common_formats(text):
    assert mentions_amount(text, 340)


@pytest.mark.parametrize("text", ["1340 EUR", "3400 EUR", "340.50 EUR", "2.340 EUR", "34 EUR", "no amount"])
def test_amount_is_not_found_inside_other_numbers(text):
    assert not mentions_amount(text, 340)


def test_amount_with_cents():
    assert mentions_amount("€23.50", 23.5)
    assert not mentions_amount("€23", 23.5)


def test_phrases_match_curly_apostrophes_and_case():
    assert contains_any("I couldn’t find that booking.", ["couldn't find"])
    assert contains_any("CLOSED on Sundays", ["closed"])


def test_money_amounts_finds_eur_amounts_only():
    text = "**€340.00** back, deposit 300 EUR, fee EUR 2,00, 50% of 80 €. Open 08:00, call +48 000 000 000, 1.5 times."
    assert money_amounts(text) == {340.0, 300.0, 2.0, 80.0}


REFUND_CALL = {
    "name": "calculate_refund",
    "input": {"booking_id": "CW-1002", "cancel_at": "2026-06-11T09:00:00+02:00"},
    "output": {"total_refund_eur": 300.0, "deposit_refund_eur": 300.0, "rental_price_eur": 80.0},
}


def test_grade_passes_a_good_answer():
    expect = {
        "tools": ["calculate_refund"],
        "not_tools": ["quote_price"],
        "tool_args": {"calculate_refund": {"booking_id": "CW-1002", "cancel_at": "2026-06-11"}},
        "amounts": [300],
        "not_amounts": [340],
    }
    checks = grade(expect, "You would get €300.00 back, of the €80 rental nothing.", [REFUND_CALL])
    assert all(c["passed"] for c in checks), checks


def test_grade_fails_wrong_amount_missing_tool_and_wrong_args():
    expect = {"tools": ["calculate_refund"], "tool_args": {"get_booking": {"booking_id": "CW-1002"}}, "amounts": [340]}
    calls = [{"name": "get_booking", "input": {"booking_id": "CW-1003"}, "output": {"found": False}}]
    checks = grade(expect, "You get 380 EUR back.", calls)
    assert [c["passed"] for c in checks] == [False, False, False, False]
    assert checks[-1]["name"] == "every EUR amount comes from a tool result"


def test_amount_the_model_calculated_itself_is_flagged():
    checks = grade({}, "Cancelling today gets you €40.00 more than tomorrow.", [REFUND_CALL])
    assert checks[-1]["passed"] is False
    assert "40.0" in checks[-1]["detail"]


def test_amount_from_an_earlier_turn_counts_as_grounded():
    earlier = {"name": "calculate_refund", "input": {}, "output": {"total_refund_eur": 340.0}}
    checks = grade({}, "Today you get €340, tomorrow €300.", [REFUND_CALL], [earlier, REFUND_CALL])
    assert checks[-1]["passed"] is True


def test_not_tools_fails_when_the_tool_was_called():
    checks = grade({"not_tools": ["calculate_refund"]}, "ok", [REFUND_CALL])
    assert checks[0]["passed"] is False


def test_grade_decline_needs_staff_contact_and_no_forbidden_fact():
    expect = {"staff_contact": True, "excludes": ["Canberra"]}
    assert all(c["passed"] for c in grade(expect, "Please contact help@citywheels.example.", []))
    assert not all(c["passed"] for c in grade(expect, "Canberra. help@citywheels.example", []))
    assert not all(c["passed"] for c in grade(expect, "It's Canberra. help@citywheels.example", []))
    assert not all(c["passed"] for c in grade(expect, "I can't help with that.", []))


def test_grade_rejects_unknown_expect_keys():
    with pytest.raises(ValueError):
        grade({"amount": [340]}, "340", [])


# ---------------------------------------------------------------- the question file itself

def test_question_file_meets_the_assignment():
    assert len(QUESTIONS) >= 10
    refunds = [q for q in QUESTIONS if "calculate_refund" in json.dumps(q["expect"].get("tools", []))]
    declines = [q for q in QUESTIONS if q["expect"].get("staff_contact")]
    assert len(refunds) >= 2
    assert len(declines) >= 2


@pytest.mark.parametrize("case", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_every_case_is_well_formed(case):
    assert case["turns"] and all(isinstance(t, str) and t for t in case["turns"])
    assert case["expect"] and set(case["expect"]) <= KNOWN_KEYS


def test_case_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))
