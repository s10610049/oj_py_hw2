import httpx
import pytest

from frontend.client import APIClient


def test_client_sends_bounded_upload_body_headers_and_params():
    seen = {}

    def handler(request):
        seen.update(
            body=request.content,
            content_type=request.headers.get("content-type"),
            query=request.url.query.decode("ascii"),
        )
        return httpx.Response(200, json={"code": 200, "msg": "ok", "data": {"id": "a1"}})

    client = APIClient("http://test", transport=httpx.MockTransport(handler))
    try:
        assert client.request(
            "POST",
            "/api/attachments/",
            content=b"hello",
            headers={"Content-Type": "text/plain"},
            params={"filename": "note.txt"},
        ) == {"id": "a1"}
    finally:
        client.close()

    assert seen == {
        "body": b"hello",
        "content_type": "text/plain",
        "query": "filename=note.txt",
    }


def test_client_rejects_ambiguous_json_and_raw_content_before_io():
    calls = []
    client = APIClient(
        "http://test",
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    )
    try:
        with pytest.raises(ValueError, match="mutually exclusive"):
            client.request("POST", "/upload", json={"a": 1}, content=b"data")
    finally:
        client.close()
    assert calls == []
