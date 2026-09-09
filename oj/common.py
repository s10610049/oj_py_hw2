"""Shared, deliberately non-sensitive API errors and response envelopes."""

from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def response(data=None, msg="success", status=200):
    return JSONResponse({"code": status, "msg": msg, "data": data}, status_code=status)
