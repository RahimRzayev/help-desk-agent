"""Command line.

    python -m citywheels "What time do you open on Saturday?"   # one question
    python -m citywheels                                         # chat, with follow-up questions
    python -m citywheels -v ...                                  # also show tool calls
"""

import argparse
import json
import sys

import anthropic
from dotenv import load_dotenv

from citywheels.agent import Agent, AgentResult
from citywheels.llm import ClaudeModel, describe_api_error


def print_result(result: AgentResult, verbose: bool) -> None:
    if verbose:
        for call in result.tool_calls:
            print(f"  [tool] {call.name}({json.dumps(call.input)})", file=sys.stderr)
            print(f"         -> {json.dumps(call.output)[:400]}", file=sys.stderr)
    print(result.answer)


def chat(agent: Agent, verbose: bool) -> None:
    print("CityWheels help desk. Ask a question, or type 'exit' to quit.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question.lower() in {"exit", "quit"}:
            return
        if not question:
            continue
        try:
            result = agent.ask(question)
        except anthropic.AnthropicError as exc:
            print(f"\n{describe_api_error(exc)}")
            continue
        print("\nCityWheels: ", end="")
        print_result(result, verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m citywheels", description="CityWheels help desk agent")
    parser.add_argument("question", nargs="*", help="the question to ask; leave out to start a chat")
    parser.add_argument("-v", "--verbose", action="store_true", help="show the tool calls")
    args = parser.parse_args(argv)

    load_dotenv()
    agent = Agent(ClaudeModel())
    if not args.question:
        chat(agent, args.verbose)
        return 0
    try:
        result = agent.ask(" ".join(args.question))
    except anthropic.AnthropicError as exc:
        print(describe_api_error(exc), file=sys.stderr)
        return 1
    print_result(result, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
