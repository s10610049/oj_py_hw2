"""Structured frontend API error contract tests."""

import httpx
import pytest

from frontend.client import APIClient, APIError


def test_api_client_preserves_structured_error_identity_and_retryability():
    client = APIClient(
        "http://test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                409,
                json={
                    "code": 409,
                    "msg": "context changed",
                    "data": {
                        "error_code": "context_epoch_mismatch",
                        "retryable": True,
                    },
                },
            )
        ),
    )
    try:
        with pytest.raises(APIError) as caught:
            client.request("POST", "/api/chat/sessions/s1/turns/", json={"message": "x"})
    finally:
        client.close()

    assert caught.value.status == 409
    assert caught.value.error_code == "context_epoch_mismatch"
    assert caught.value.retryable is True
