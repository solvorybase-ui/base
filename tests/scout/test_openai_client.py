import json
from types import SimpleNamespace

import pytest

from backend.scout.openai_client import (
    MODEL_NAME,
    MAX_IMAGE_INPUTS,
    MissingOpenAIAPIKeyError,
    OpenAIResponseError,
    OpenAIResponsesScoutClient,
    SCOUT_OUTPUT_JSON_SCHEMA,
    get_openai_api_key,
)


VALID = {
    "variant_id": "v1",
    "decision": "selected",
    "reason": "Useful and functionally distinct.",
    "usefulness": "high",
    "functional_distinction": "clear",
    "functional_distinction_summary": "Distinct mechanism.",
}


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeSDK:
    def __init__(self, output_text=json.dumps(VALID)):
        self.responses = FakeResponses(output_text)


def test_uses_approved_model_responses_api_and_strict_json_schema():
    sdk = FakeSDK()
    client = OpenAIResponsesScoutClient(sdk_client=sdk)

    result = client.evaluate(prompt="PROMPT")

    assert result == VALID
    assert len(sdk.responses.calls) == 1
    call = sdk.responses.calls[0]
    assert call["model"] == MODEL_NAME == "gpt-5.6-luna"
    assert call["text"] == {
        "format": {
            "type": "json_schema",
            "name": "solvory_product_scout_v1",
            "schema": SCOUT_OUTPUT_JSON_SCHEMA,
            "strict": True,
        }
    }


def test_sends_up_to_three_product_images_as_real_image_inputs():
    sdk = FakeSDK()
    client = OpenAIResponsesScoutClient(sdk_client=sdk)
    urls = [f"https://example.test/{i}.jpg" for i in range(5)]

    client.evaluate(prompt="PROMPT", image_urls=urls)

    content = sdk.responses.calls[0]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "PROMPT"}
    assert content[1:] == [
        {"type": "input_image", "image_url": url}
        for url in urls[:MAX_IMAGE_INPUTS]
    ]
    assert len(content[1:]) == 3


def test_empty_image_values_are_not_sent():
    sdk = FakeSDK()
    client = OpenAIResponsesScoutClient(sdk_client=sdk)

    client.evaluate(prompt="PROMPT", image_urls=("", "https://example.test/a.jpg"))

    content = sdk.responses.calls[0]["input"][0]["content"]
    assert content == [
        {"type": "input_text", "text": "PROMPT"},
        {"type": "input_image", "image_url": "https://example.test/a.jpg"},
    ]


def test_missing_api_key_helper_is_clear(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingOpenAIAPIKeyError, match="OPENAI_API_KEY"):
        get_openai_api_key()


def test_api_key_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "  test-key  ")
    assert get_openai_api_key() == "test-key"


def test_invalid_json_response_is_provider_adapter_error():
    client = OpenAIResponsesScoutClient(sdk_client=FakeSDK("not-json"))
    with pytest.raises(OpenAIResponseError, match="not valid JSON"):
        client.evaluate(prompt="PROMPT")


def test_missing_output_text_is_provider_adapter_error():
    client = OpenAIResponsesScoutClient(sdk_client=FakeSDK(""))
    with pytest.raises(OpenAIResponseError, match="output_text"):
        client.evaluate(prompt="PROMPT")
