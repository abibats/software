import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import server


class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None

    def request(self, method, path, body=None, token=True, query=None):
        if query:
            path = f"{path}?{urlencode(query)}"
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                return exc.code, payload
            finally:
                exc.close()

    def login(self, username, password="123456"):
        status, payload = self.request(
            "POST",
            "/api/login",
            {"username": username, "password": password},
            token=False,
        )
        if status == 200:
            self.token = payload["token"]
        return status, payload


class StudySeatApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_db_path = server.DB_PATH
        server.DB_PATH = Path(self.tmp.name) / "test_study_seat.db"
        server.TOKENS.clear()
        server.init_db()

        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.client = ApiClient(f"http://{host}:{port}")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        server.DB_PATH = self.original_db_path
        server.TOKENS.clear()
        self.tmp.cleanup()

    def future_hour(self):
        return (datetime.now() + timedelta(days=1)).replace(
            minute=0, second=0, microsecond=0
        )

    def active_seat_id(self):
        status, payload = self.client.request(
            "GET", "/api/seats", query={"status": "active"}
        )
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["seats"]), 0)
        return payload["seats"][0]["id"]

    def test_login_success_and_failure(self):
        status, payload = self.client.login("student1")
        self.assertEqual(status, 200)
        self.assertIn("token", payload)
        self.assertEqual(payload["user"]["username"], "student1")

        bad_client = ApiClient(self.client.base_url)
        status, payload = bad_client.login("student1", "wrong-password")
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_api_requires_bearer_token(self):
        status, payload = self.client.request("GET", "/api/me", token=False)
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_student_cannot_create_room_but_manager_can(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "POST",
            "/api/rooms",
            {
                "name": "Test Room",
                "building": "Test Building",
                "department": "All",
                "daily_code": "T101",
            },
        )
        self.assertEqual(status, 403)
        self.assertIn("error", payload)

        manager = ApiClient(self.client.base_url)
        manager.login("manager")
        status, payload = manager.request(
            "POST",
            "/api/rooms",
            {
                "name": "Test Room",
                "building": "Test Building",
                "department": "All",
                "daily_code": "T101",
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        status, payload = manager.request("GET", "/api/rooms")
        self.assertEqual(status, 200)
        self.assertTrue(any(room["name"] == "Test Room" for room in payload["rooms"]))

    def test_reservation_rejects_overlap_for_same_seat(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 2},
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 409)
        self.assertIn("error", payload)

    def test_reservation_can_be_checked_in_with_room_code(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        status, _ = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 200)

        status, payload = self.client.request("GET", "/api/reservations")
        self.assertEqual(status, 200)
        reservation = payload["reservations"][0]

        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {
                "reservation_id": reservation["id"],
                "code": reservation["daily_code"].lower(),
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        status, payload = self.client.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        self.assertEqual(payload["stats"]["my_checked_in"], 1)

    def test_admin_can_update_parameters(self):
        self.client.login("admin")
        status, payload = self.client.request(
            "PUT", "/api/parameters", {"key": "max_hours", "value": "3"}
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        status, payload = self.client.request("GET", "/api/parameters")
        self.assertEqual(status, 200)
        max_hours = next(p for p in payload["parameters"] if p["key"] == "max_hours")
        self.assertEqual(max_hours["value"], "3")


if __name__ == "__main__":
    unittest.main()
