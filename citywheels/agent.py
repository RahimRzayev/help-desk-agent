"""The agent loop: the model picks tools, our code runs them, repeat until a final answer."""

import json
from dataclasses import dataclass, field

from citywheels.config import STAFF_CONTACT
from citywheels.prompts import SYSTEM_PROMPT
from citywheels.tools import TOOL_SCHEMAS, run_tool

FALLBACK_ANSWER = f"Sorry, I can't answer that right now. Please contact the CityWheels staff: {STAFF_CONTACT}."


@dataclass
class ToolCall:
    name: str
    input: dict
    output: dict


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    steps: int = 0


class Agent:
    def __init__(self, model, max_steps: int = 8):
        self.model = model  # anything with create(system, messages, tools), e.g. ClaudeModel
        self.max_steps = max_steps
        self.messages: list[dict] = []  # the whole conversation, so follow-up questions work

    def ask(self, question: str) -> AgentResult:
        turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": question})
        tool_calls: list[ToolCall] = []

        for step in range(1, self.max_steps + 1):
            response = self.model.create(system=SYSTEM_PROMPT, messages=self.messages, tools=TOOL_SCHEMAS)
            if response.stop_reason == "refusal":
                break

            # Keep the full content (thinking blocks included) and never edit it later:
            # the API rejects replayed thinking blocks whose earlier history changed.
            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
                if not answer:
                    break
                return AgentResult(answer, tool_calls, response.stop_reason, step)

            # Run every requested tool and send all results back in one message.
            results = []
            for block in tool_uses:
                output = run_tool(block.name, block.input)
                tool_calls.append(ToolCall(block.name, block.input, output))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(output),
                    "is_error": "error" in output,
                })
            self.messages.append({"role": "user", "content": results})

        # Refusal, empty answer or too many steps: drop this turn so later turns start clean.
        del self.messages[turn_start:]
        return AgentResult(FALLBACK_ANSWER, tool_calls, response.stop_reason, step)
