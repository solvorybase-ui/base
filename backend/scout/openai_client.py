"""Product Scout V1 OpenAI Responses API adapter.

The adapter owns only provider-specific request/response handling. Product Scout
business rules and the second-line local output validation remain outside this
module.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping, Protocol, Sequence

MODEL_NAME = "gpt-5.6-luna"
MAX_IMAGE_INPUTS = 3

SCOUT_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "variant_id": {"type": "string", "minLength": 1},
        "decision": {"type": "string", "enum": ["selected", "rejected"]},
        "reason": {"type": "string", "minLength": 1},
        "usefulness": {"type": "string", "enum": ["low", "medium", "high"]},
        "functional_distinction": {
            "type": "string",
            "enum": ["none", "weak", "clear"],
        },
        "functional_distinction_summary": {"type": "string", "minLength": 1},
    },
    "required": [
        "variant_id",
        "decision",
        "reason",
        "usefulness",
        "functional_distinction",
        "functional_distinction_summary",
    ],
    "additionalProperties": False,
}


class ScoutAIClient(Protocol):
    def evaluate(
        self, *, prompt: str, image_urls: Sequence[str] = ()
    ) -> Mapping[str, Any]: ...


class MissingOpenAIAPIKeyError(RuntimeError):
    pass


class OpenAIResponseError(RuntimeError):
    pass


def get_openai_api_key() -> str:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise MissingOpenAIAPIKeyError(
            "OPENAI_API_KEY environment variable is required"
        )
    return value


class OpenAIResponsesScoutClient:
    """Synchronous Product Scout adapter for the OpenAI Responses API.

    ``sdk_client`` is injectable for tests. In production, omitting it creates the
    official OpenAI Python SDK client with the API key read exclusively from
    ``OPENAI_API_KEY``.
    """

    model_name = MODEL_NAME

    def __init__(self, *, sdk_client: Any | None = None) -> None:
        if sdk_client is None:
            # Lazy import keeps unit tests independent from a live SDK/API.
            from openai import OpenAI

            sdk_client = OpenAI(api_key=get_openai_api_key())
        self._client = sdk_client

    def evaluate(
        self, *, prompt: str, image_urls: Sequence[str] = ()
    ) -> Mapping[str, Any]:
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": prompt}
        ]
        for image_url in tuple(image_urls)[:MAX_IMAGE_INPUTS]:
            if image_url:
                content.append(
                    {"type": "input_image", "image_url": str(image_url)}
                )

        response = self._client.responses.create(
            model=self.model_name,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "solvory_product_scout_v1",
                    "schema": SCOUT_OUTPUT_JSON_SCHEMA,
                    "strict": True,
                }
            },
        )

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise OpenAIResponseError("OpenAI response did not contain output_text")

        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise OpenAIResponseError(
                "OpenAI response output_text was not valid JSON"
            ) from exc

        if not isinstance(parsed, dict):
            raise OpenAIResponseError("OpenAI structured output was not an object")
        return parsed
