"""One HTTP client and cookie jar per Streamlit session."""

import os
from urllib.parse import quote

import httpx


class APIError(Exception):
    """Safe error for presentation; never contains response bodies or credentials."""

    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def resource(value):
    return quote(str(value), safe="")


class APIClient:
    def __init__(self, base_url=None, *, transport=None):
        self.http = httpx.Client(
            base_url=(base_url or os.environ.get("OJ_API_URL", "http://127.0.0.1:8000")).rstrip(
                "/"
            ),
            timeout=httpx.Timeout(12.0, connect=4.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def request(self, method, path, *, json=None, content=None, headers=None, params=None):
        if json is not None and content is not None:
            raise ValueError("json and content are mutually exclusive")
        try:
            response = self.http.request(
                method,
                path,
                json=json,
                content=content,
                headers=headers,
                params=params,
            )
        except httpx.TimeoutException:
            raise APIError(0, "请求超时。请重试查询；写入请求可能已处理，请先核对结果。") from None
        except httpx.HTTPError:
            raise APIError(0, "暂时无法连接服务，请确认后端已启动后重试。") from None
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            raise APIError(502, "服务返回了无法识别的响应，请稍后重试。") from None
        if (
            not isinstance(body, dict)
            or type(body.get("code")) is not int
            or body["code"] != response.status_code
            or not isinstance(body.get("msg"), str)
            or "data" not in body
        ):
            raise APIError(502, "服务响应格式不符合约定，请联系管理员。")
        if response.status_code != 200:
            message = body["msg"]
            if isinstance(json, dict):
                for field in ("password", "api_key"):
                    secret = json.get(field)
                    if secret:
                        message = message.replace(str(secret), "[已隐藏]")
            if response.status_code == 401:
                self.http.cookies.clear()
            raise APIError(response.status_code, message[:400])
        return body["data"]

    def close(self):
        self.http.cookies.clear()
        self.http.close()
