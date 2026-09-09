import copy

import httpx
import pytest

from oj.ai import AIService
from oj.common import APIError

MODEL_CONFIG = {
    "provider_url": "https://models.example/v1",
    "model": "example-model",
    "api_key": "synthetic-internal-test-key",
    "input_price": 1,
    "output_price": 2,
    "price_unit": 1_000_000,
    "currency": "USD",
}


@pytest.mark.asyncio
async def test_internal_config_is_an_isolated_copy_and_never_changes_public_shape():
    service = AIService(MODEL_CONFIG, transport=httpx.MockTransport(lambda _: None))
    try:
        internal = service.private_config("alice")
        internal["api_key"] = "changed"
        assert service.private_config("alice")["api_key"] == MODEL_CONFIG["api_key"]
        public = await service.get_config("alice")
        assert "api_key" not in public
        assert public["api_key_configured"] is True
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_trusted_authoring_prompt_has_separate_bounded_limit():
    service = AIService(MODEL_CONFIG, transport=httpx.MockTransport(lambda _: None))
    long_prompt = "a" * 20_001
    try:
        with pytest.raises(APIError):
            await service.start("alice", long_prompt)
        task = await service.start_authoring("alice", copy.copy(long_prompt))
        assert task["status"] == "pending"
        with pytest.raises(APIError):
            await service.start_authoring("alice", "a" * 160_001)
    finally:
        await service.close()
