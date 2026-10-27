"""Automatic graders for one evaluation case. Pure functions, unit-tested in tests/test_eval_checks.py.

`expect` keys (all optional):
    tools          each item is a tool name, or a list of names of which at least one must be called
    not_tools      tools that must not be called
    tool_args      {tool: {arg: value}}: some call of that tool has these arguments
                   (string values match as a case-insensitive prefix, e.g. "2026-06-11")
    amounts        numbers the answer must state (340 matches "340", "340.00", "€340", "340,00 EUR")
    not_amounts    numbers the answer must not state
    contains_any   list of phrase groups; the answer must contain one phrase of every group
    excludes       phrases the answer must not contain
    not_found      the answer must say the booking was not found
    staff_contact  the answer must give the staff email or phone
Only the tool calls of the last turn are graded.

Every case also gets one automatic check: each EUR amount in the answer must appear in some
tool result of the conversation. It catches amounts the model made up or calculated itself.
"""

import json
import re

STAFF_CONTACT_MARKERS = ["help@citywheels.example", "+48 000 000 000"]
NOT_FOUND_PHRASES = [
    "not found", "couldn't find", "could not find", "can't find", "cannot find", "unable to find",
    "didn't find", "did not find", "no booking", "doesn't exist", "does not exist", "wasn't able to find",
]
KNOWN_KEYS = {
    "tools", "not_tools", "tool_args", "amounts", "not_amounts", "contains_any", "excludes", "not_found", "staff_contact",
}
NUMBER = r"\d+(?:[.,]\d{1,2})?"
MONEY = re.compile(rf"(?:€|\bEUR|\beuros?)\s*({NUMBER})|({NUMBER})\s*(?:€|EUR\b|euros?\b)", re.IGNORECASE)


def _normalize(text: str) -> str:
    return text.lower().replace("’", "'").replace(" ", " ")


def contains_any(text: str, phrases: list[str]) -> bool:
    text = _normalize(text)
    return any(_normalize(p) in text for p in phrases)


def mentions_amount(text: str, amount: float) -> bool:
    whole, _, fraction = f"{amount:.2f}".partition(".")
    fraction = fraction.rstrip("0")
    tail = rf"[.,]{fraction}0?" if fraction else r"(?:[.,]00?)?"
    # Not part of a bigger number: no digit or decimal separator before, no digit or decimals after.
    pattern = rf"(?<![\d.,]){whole}{tail}(?!\d|[.,]\d)"
    return re.search(pattern, text) is not None


def _to_float(number: str) -> float:
    return round(float(number.replace(",", ".")), 2)


def money_amounts(text: str) -> set[float]:
    """EUR amounts written in the text: '€40.00', '40 EUR', 'EUR 40,50'."""
    return {_to_float(a or b) for a, b in MONEY.findall(text.replace(" ", " "))}


def numbers_in(outputs: list) -> set[float]:
    """Every number in the tool outputs, including numbers inside text such as policy sections."""
    return {_to_float(n) for n in re.findall(r"\d+(?:\.\d+)?", json.dumps(outputs))}


def _args_match(expected: dict, actual: dict) -> bool:
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, str):
            if not isinstance(got, str) or not got.lower().startswith(want.lower()):
                return False
        elif got != want:
            return False
    return True


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def grade(expect: dict, answer: str, tool_calls: list[dict], all_tool_calls: list[dict] | None = None) -> list[dict]:
    """Return one {name, passed, detail} per expectation.

    tool_calls are those of the last turn; all_tool_calls (default: the same) those of the whole conversation.
    """
    unknown = set(expect) - KNOWN_KEYS
    if unknown:
        raise ValueError(f"Unknown expect keys: {sorted(unknown)}")
    if all_tool_calls is None:
        all_tool_calls = tool_calls

    called = [c["name"] for c in tool_calls]
    called_text = ", ".join(called) or "no tools"
    checks = []

    for tool in expect.get("tools", []):
        options = [tool] if isinstance(tool, str) else tool
        checks.append(_check(f"calls {' or '.join(options)}", any(o in called for o in options), f"called: {called_text}"))

    for tool in expect.get("not_tools", []):
        checks.append(_check(f"does not call {tool}", tool not in called, f"called: {called_text}"))

    for tool, args in expect.get("tool_args", {}).items():
        inputs = [c["input"] for c in tool_calls if c["name"] == tool]
        checks.append(_check(f"{tool} gets {args}", any(_args_match(args, i) for i in inputs), f"inputs: {inputs}"))

    for amount in expect.get("amounts", []):
        checks.append(_check(f"states {amount:g} EUR", mentions_amount(answer, amount)))

    for amount in expect.get("not_amounts", []):
        checks.append(_check(f"does not state {amount:g} EUR", not mentions_amount(answer, amount)))

    for group in expect.get("contains_any", []):
        checks.append(_check(f"mentions one of {group}", contains_any(answer, group)))

    for phrase in expect.get("excludes", []):
        checks.append(_check(f"does not say {phrase!r}", not contains_any(answer, [phrase])))

    if expect.get("not_found"):
        checks.append(_check("says the booking was not found", contains_any(answer, NOT_FOUND_PHRASES)))

    if expect.get("staff_contact"):
        checks.append(_check("gives the staff contact", contains_any(answer, STAFF_CONTACT_MARKERS)))

    ungrounded = sorted(money_amounts(answer) - numbers_in([c["output"] for c in all_tool_calls]))
    checks.append(_check(
        "every EUR amount comes from a tool result", not ungrounded, f"not in any tool result: {ungrounded}"
    ))
    return checks
