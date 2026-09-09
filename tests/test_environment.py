"""Check the development dependencies without using real credentials or services."""

import importlib
import sys
from io import StringIO

import bcrypt
import httpx
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI


def test_supported_python_version():
    assert sys.version_info >= (3, 10)


@pytest.mark.parametrize(
    "module_name",
    ["bcrypt", "dotenv", "fastapi", "httpx", "psutil", "streamlit", "uvicorn"],
)
def test_runtime_dependency_imports(module_name):
    assert importlib.import_module(module_name) is not None


@pytest.mark.asyncio
async def test_async_fastapi_httpx_transport():
    application = FastAPI()

    @application.get("/environment-check")
    async def environment_check():
        return {"status": "ok"}

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/environment-check")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_bcrypt_verifies_only_the_matching_password():
    password = b"synthetic-test-password"
    # Low cost keeps this dependency smoke test fast; not an application setting.
    password_hash = bcrypt.hashpw(password, bcrypt.gensalt(rounds=4))
    assert bcrypt.checkpw(password, password_hash)
    assert not bcrypt.checkpw(b"incorrect-password", password_hash)


def test_dotenv_parses_a_synthetic_stream_without_reading_local_secrets():
    configuration = dotenv_values(stream=StringIO("EXAMPLE_SETTING=local-test\n"))
    assert configuration == {"EXAMPLE_SETTING": "local-test"}
