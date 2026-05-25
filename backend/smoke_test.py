import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
USERNAME = os.environ.get("SMOKE_USERNAME", "student1")
PASSWORD = os.environ.get("SMOKE_PASSWORD", "123456")


def request(method, path, body=None, token=None, query=None):
    if query:
        path = f"{path}?{urlencode(query)}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except json.JSONDecodeError:
            payload = {"error": exc.reason}
        finally:
            exc.close()
        return exc.code, payload


def assert_status(name, status, payload, expected=200):
    if status != expected:
        raise AssertionError(f"{name} failed: expected {expected}, got {status}, payload={payload}")
    print(f"[OK] {name}")


def main():
    if not BASE_URL:
        raise SystemExit("SMOKE_BASE_URL is required, for example: https://example.com")

    status, payload = request(
        "POST",
        "/api/login",
        {"username": USERNAME, "password": PASSWORD},
    )
    assert_status("login", status, payload)
    token = payload.get("token")
    if not token:
        raise AssertionError("login response did not include token")

    status, payload = request("GET", "/api/me", token=token)
    assert_status("current user", status, payload)
    if payload.get("user", {}).get("username") != USERNAME:
        raise AssertionError(f"unexpected user payload: {payload}")

    status, payload = request("GET", "/api/stats", token=token)
    assert_status("stats", status, payload)
    for key in ("rooms", "seats"):
        if key not in payload.get("stats", {}):
            raise AssertionError(f"stats response missing {key}: {payload}")

    status, payload = request("GET", "/api/seats", token=token, query={"status": "active"})
    assert_status("active seats", status, payload)
    if "seats" not in payload:
        raise AssertionError(f"seats response missing seats list: {payload}")

    print("Smoke test passed.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, URLError, TimeoutError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
