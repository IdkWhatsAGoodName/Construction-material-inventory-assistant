"""Narrow Gemini Interactions API adapter with no automatic tool execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when the conversational provider is unavailable or returns invalid data."""


@dataclass(frozen=True, slots=True)
class ProposedCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderTurn:
    steps: tuple[dict[str, Any], ...]
    calls: tuple[ProposedCall, ...]


class ConversationProvider(Protocol):
    async def route(
        self,
        *,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_instruction: str,
    ) -> ProviderTurn: ...

    async def comment(self, *, user_message: str, verified_results: list[str]) -> str: ...

    async def close(self) -> None: ...


class GeminiInteractionsProvider:
    """Google Gen AI SDK wrapper that exposes only declarative tools."""

    def __init__(self, *, api_key: str, model: str, timeout_ms: int = 20_000) -> None:
        from google import genai
        from google.genai import types

        self._model = model
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )

    async def route(
        self,
        *,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_instruction: str,
    ) -> ProviderTurn:
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                input=history,
                tools=tools,
                store=False,
                system_instruction=system_instruction,
                generation_config={"tool_choice": "any"},
            )
        except Exception as error:
            raise ProviderError("Gemini routing request failed") from error

        returned_steps = getattr(interaction, "steps", None)
        if not isinstance(returned_steps, (list, tuple)):
            raise ProviderError("Gemini response did not contain interaction steps")
        steps = tuple(_serialize_step(step) for step in returned_steps)
        calls: list[ProposedCall] = []
        for raw, step in zip(steps, returned_steps, strict=True):
            if raw.get("type") != "function_call":
                continue
            arguments = getattr(step, "arguments", raw.get("arguments", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"__invalid_json__": arguments}
            if not isinstance(arguments, dict):
                arguments = {"__invalid_arguments__": arguments}
            calls.append(
                ProposedCall(
                    id=str(getattr(step, "id", raw.get("id", ""))),
                    name=str(getattr(step, "name", raw.get("name", ""))),
                    arguments=arguments,
                )
            )
        return ProviderTurn(steps=steps, calls=tuple(calls))

    async def comment(self, *, user_message: str, verified_results: list[str]) -> str:
        result_text = "\n\n".join(verified_results)
        prompt = f"User request:\n{user_message}\n\nVerified application results:\n{result_text}"
        instruction = (
            "Write one concise conversational comment about the verified results. The verified "
            "result boxes are authoritative. Do not add facts, calculations, numbers, dates, "
            "times, prices, currencies, quantities, SKUs, or conclusions absent from those "
            "results. Do not use Markdown."
        )
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                input=prompt,
                tools=[],
                store=False,
                system_instruction=instruction,
                generation_config={"tool_choice": "none"},
            )
        except Exception as error:
            raise ProviderError("Gemini commentary request failed") from error
        text = getattr(interaction, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Gemini commentary was empty")
        return text.strip()

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _serialize_step(step: Any) -> dict[str, Any]:
    if hasattr(step, "model_dump"):
        return step.model_dump(mode="json", exclude_none=True)
    if isinstance(step, dict):
        return dict(step)
    raise ProviderError("Gemini returned an unserializable interaction step")
