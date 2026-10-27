"""Thin wrapper around the Anthropic API.

The agent only calls `create()`, so tests can pass in a fake model with the same method.
"""

import os

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"


class ClaudeModel:
    def __init__(self, model: str | None = None, effort: str | None = None, client: anthropic.Anthropic | None = None):
        self.model = model or os.environ.get("CITYWHEELS_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.environ.get("CITYWHEELS_EFFORT") or DEFAULT_EFFORT
        self.client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def create(self, system: str, messages: list, tools: list):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            # Tools and system prompt are the same on every request, so cache them.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            # Opus 5.5 always thinks; effort sets how much (and so cost and latency).
            output_config={"effort": self.effort},
            # If a safety classifier declines, retry on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )


def describe_api_error(exc: anthropic.AnthropicError) -> str:
    """Short, user-facing explanation of an API failure."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "The API key was rejected. Check ANTHROPIC_API_KEY in your .env file."
    if isinstance(exc, anthropic.RateLimitError):
        return "Too many requests to the model right now. Wait a minute and try again."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the model API. Check your internet connection."
    if isinstance(exc, anthropic.APIStatusError):
        return f"The model API returned an error ({exc.status_code}): {exc.message}"
    return f"Could not call the model API: {exc}. Is ANTHROPIC_API_KEY set in .env?"
