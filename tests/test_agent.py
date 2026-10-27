"""Tests of the agent loop with a fake model: no network, no API key."""

import inspect
import json
from types import SimpleNamespace

from citywheels.agent import FALLBACK_ANSWER, Agent
from citywheels.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS


def text(s):
    return SimpleNamespace(type="text", text=s)


def thinking():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def tool_use(id, name, **input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def reply(*blocks, stop_reason=None):
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class FakeModel:
    """Replays scripted responses and records what the agent sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, system, messages, tools):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        return self.responses.pop(0)


def tool_results_sent(call):
    last = call["messages"][-1]
    assert last["role"] == "user"
    return last["content"]


def test_tool_result_goes_back_to_the_model_until_it_answers():
    model = FakeModel(
        reply(thinking(), tool_use("t1", "calculate_refund", booking_id="CW-1002", cancel_at=None)),
        reply(text("You get 340 EUR back.")),
    )
    result = Agent(model).ask("I want to cancel CW-1002. How much do I get back?")

    assert result.answer == "You get 340 EUR back."
    assert result.steps == 2
    assert [c.name for c in result.tool_calls] == ["calculate_refund"]
    assert result.tool_calls[0].output["total_refund_eur"] == 340.0

    [sent] = tool_results_sent(model.calls[1])
    assert sent["tool_use_id"] == "t1"
    assert sent["is_error"] is False
    assert json.loads(sent["content"])["total_refund_eur"] == 340.0
    # The assistant turn, thinking block included, is replayed unchanged.
    assert model.calls[1]["messages"][1]["content"][0].type == "thinking"


def test_unknown_booking_is_passed_back_to_the_model_without_crashing():
    model = FakeModel(
        reply(tool_use("t1", "get_booking", booking_id="CW-9999")),
        reply(text("I could not find booking CW-9999.")),
    )
    result = Agent(model).ask("What is in booking CW-9999?")

    assert result.answer == "I could not find booking CW-9999."
    [sent] = tool_results_sent(model.calls[1])
    assert json.loads(sent["content"])["found"] is False


def test_several_tool_calls_in_one_turn_are_answered_in_one_message():
    model = FakeModel(
        reply(
            tool_use("t1", "get_booking", booking_id="CW-1001"),
            tool_use("t2", "search_policies", query="cancellation refund"),
        ),
        reply(text("Done.")),
    )
    Agent(model).ask("Tell me about CW-1001 and the refund rules.")

    sent = tool_results_sent(model.calls[1])
    assert [r["tool_use_id"] for r in sent] == ["t1", "t2"]


def test_unknown_tool_is_reported_to_the_model_as_an_error():
    model = FakeModel(
        reply(tool_use("t1", "delete_all_bookings")),
        reply(text("Sorry, I can't do that.")),
    )
    result = Agent(model).ask("Delete everything.")

    [sent] = tool_results_sent(model.calls[1])
    assert sent["is_error"] is True
    assert result.answer == "Sorry, I can't do that."


def test_loop_stops_after_max_steps():
    model = FakeModel(*[reply(tool_use(f"t{i}", "search_policies", query="hours")) for i in range(3)])
    agent = Agent(model, max_steps=3)
    result = agent.ask("Loop forever.")

    assert result.answer == FALLBACK_ANSWER
    assert result.steps == 3
    assert len(model.calls) == 3
    assert agent.messages == []


def test_refusal_returns_the_staff_contact_and_forgets_that_turn():
    model = FakeModel(reply(text("Hello!")), reply(stop_reason="refusal"))
    agent = Agent(model)
    agent.ask("Hi")
    result = agent.ask("Something the safety classifier declines.")

    assert result.answer == FALLBACK_ANSWER
    assert "help@citywheels.example" in result.answer
    assert len(agent.messages) == 2  # only the first turn is kept


def test_empty_final_answer_falls_back_to_the_staff_contact():
    result = Agent(FakeModel(reply(thinking()))).ask("...")
    assert result.answer == FALLBACK_ANSWER


def test_follow_up_question_sees_the_earlier_turns():
    model = FakeModel(
        reply(tool_use("t1", "calculate_refund", booking_id="CW-1002", cancel_at=None)),
        reply(text("340 EUR.")),
        reply(tool_use("t2", "calculate_refund", booking_id="CW-1002", cancel_at="2026-06-11T09:00:00+02:00")),
        reply(text("300 EUR.")),
    )
    agent = Agent(model)
    agent.ask("How much do I get back if I cancel CW-1002?")
    result = agent.ask("And what if I cancel tomorrow instead?")

    history = model.calls[2]["messages"]
    assert history[0]["content"] == "How much do I get back if I cancel CW-1002?"
    assert history[-1]["content"] == "And what if I cancel tomorrow instead?"
    assert result.tool_calls[0].output["total_refund_eur"] == 300.0
    assert result.answer == "300 EUR."


def test_every_request_sends_the_system_prompt_and_all_tools():
    model = FakeModel(reply(text("Hi.")))
    Agent(model).ask("Hi")

    call = model.calls[0]
    assert "10 June 2026" in call["system"]
    assert {t["name"] for t in call["tools"]} == set(TOOL_FUNCTIONS)


def test_tool_schemas_match_the_python_functions():
    for schema in TOOL_SCHEMAS:
        params = inspect.signature(TOOL_FUNCTIONS[schema["name"]]).parameters
        properties = schema["input_schema"]["properties"]
        assert set(properties) <= set(params), schema["name"]
        needed = {n for n, p in params.items() if p.default is inspect.Parameter.empty}
        assert needed <= set(schema["input_schema"]["required"]), schema["name"]
        assert schema["input_schema"]["additionalProperties"] is False
