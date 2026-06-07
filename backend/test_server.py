import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
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


class FakeApiResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class StudySeatApiTest(unittest.TestCase):
    def setUp(self):
        self.original_env = {
            key: os.environ.get(key)
            for key in ("MIMO_API_KEY", "MIMO_API_URL", "MIMO_MODEL", "AI_API_KEY")
        }
        for key in self.original_env:
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_db_path = server.DB_PATH
        self.original_config_path = server.CONFIG_PATH
        server.DB_PATH = Path(self.tmp.name) / "test_study_seat.db"
        server.CONFIG_PATH = Path(self.tmp.name) / "config.json"
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
        server.CONFIG_PATH = self.original_config_path
        server.TOKENS.clear()
        self.tmp.cleanup()
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

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

    def test_checkin_rejects_before_start_time(self):
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
        reservation = payload["reservations"][0]

        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {"reservation_id": reservation["id"], "code": reservation["daily_code"]},
        )
        self.assertEqual(status, 400)
        self.assertIn("还未到预约开始时间", payload["error"])

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

    def test_assistant_falls_back_without_api_key(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "POST", "/api/assistant", {"message": "怎么签到"}
        )
        self.assertEqual(status, 200)
        self.assertIn("reply", payload)
        self.assertNotEqual(payload.get("source"), "api")

    def test_assistant_uses_mimo_api_when_configured(self):
        self.client.login("student1")
        os.environ["MIMO_API_KEY"] = "test-key"
        os.environ["MIMO_API_URL"] = "https://example.test/chat/completions"
        os.environ["MIMO_MODEL"] = "mimo-v2.5"

        fake_payload = {
            "choices": [
                {"message": {"content": "可以，我已经根据当前座位数据为你筛选。"}}
            ]
        }
        with patch("server.urlopen", return_value=FakeApiResponse(fake_payload)) as mocked_urlopen:
            status, payload = self.client.request(
                "POST", "/api/assistant", {"message": "帮我找一个靠窗座位"}
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "api")
        self.assertEqual(payload["reply"], "可以，我已经根据当前座位数据为你筛选。")
        self.assertTrue(mocked_urlopen.called)

    def test_assistant_uses_config_file_when_present(self):
        self.client.login("student1")
        server.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "mimo_api_key": "config-key",
                    "mimo_api_url": "https://example.test/from-config",
                    "mimo_api_format": "openai",
                    "mimo_model": "mimo-v2.5",
                }
            ),
            encoding="utf-8",
        )

        fake_payload = {
            "choices": [
                {"message": {"content": "这是从配置文件启用的智能助手回复。"}}
            ]
        }
        with patch("server.urlopen", return_value=FakeApiResponse(fake_payload)) as mocked_urlopen:
            status, payload = self.client.request(
                "POST", "/api/assistant", {"message": "今晚还有空座吗"}
            )

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "api")
        self.assertEqual(payload["reply"], "这是从配置文件启用的智能助手回复。")
        self.assertEqual(request.full_url, "https://example.test/from-config")

    def test_config_file_allows_utf8_bom(self):
        server.CONFIG_PATH.write_text(
            json.dumps({"mimo_api_key": "config-key"}),
            encoding="utf-8-sig",
        )

        self.assertTrue(server.assistant_api_configured())

    def test_assistant_supports_anthropic_token_plan_endpoint(self):
        self.client.login("student1")
        server.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "mimo_api_key": "config-key",
                    "mimo_api_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
                    "mimo_api_format": "anthropic",
                    "mimo_model": "mimo-v2.5",
                }
            ),
            encoding="utf-8",
        )

        fake_payload = {
            "content": [
                {"type": "text", "text": "Anthropic 兼容接口已经返回。"}
            ]
        }
        with patch("server.urlopen", return_value=FakeApiResponse(fake_payload)) as mocked_urlopen:
            status, payload = self.client.request(
                "POST", "/api/assistant", {"message": "帮我找安静座位"}
            )

        request = mocked_urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "api")
        self.assertEqual(payload["reply"], "Anthropic 兼容接口已经返回。")
        self.assertEqual(
            request.full_url,
            "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages",
        )
        self.assertEqual(body["max_tokens"], 600)
        self.assertIn("system", body)

    def test_cancel_reservation(self):
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
            "PUT", "/api/reservations", {"id": reservation["id"]}
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        status, payload = self.client.request("GET", "/api/reservations")
        cancelled = next(
            r for r in payload["reservations"] if r["id"] == reservation["id"]
        )
        self.assertEqual(cancelled["status"], "cancelled")

    def test_cancel_other_user_reservation_forbidden(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        status, payload = self.client.request("GET", "/api/reservations")
        reservation_id = payload["reservations"][0]["id"]

        other = ApiClient(self.client.base_url)
        other.login("student2")
        status, payload = other.request(
            "PUT", "/api/reservations", {"id": reservation_id}
        )
        self.assertEqual(status, 403)

    def test_seat_crud(self):
        manager = ApiClient(self.client.base_url)
        manager.login("manager")

        status, payload = manager.request(
            "POST",
            "/api/seats",
            {
                "room_id": 1,
                "code": "T-99",
                "near_window": True,
                "has_power": True,
                "quiet_zone": False,
            },
        )
        self.assertEqual(status, 200)

        status, payload = manager.request(
            "GET", "/api/seats", query={"keyword": "T-99"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["seats"]), 1)
        seat = payload["seats"][0]
        self.assertEqual(seat["code"], "T-99")
        self.assertEqual(seat["near_window"], 1)
        self.assertEqual(seat["has_power"], 1)

        status, payload = manager.request(
            "PUT",
            "/api/seats",
            {"id": seat["id"], "room_id": 1, "code": "T-99-MOD", "quiet_zone": True},
        )
        self.assertEqual(status, 200)

        status, payload = manager.request(
            "GET", "/api/seats", query={"keyword": "T-99"}
        )
        self.assertEqual(payload["seats"][0]["code"], "T-99-MOD")

    def test_student_cannot_manage_seats(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "POST",
            "/api/seats",
            {"room_id": 1, "code": "HACK-01"},
        )
        self.assertEqual(status, 403)

    def test_user_role_management(self):
        admin = ApiClient(self.client.base_url)
        admin.login("admin")

        status, payload = admin.request("GET", "/api/users")
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["users"]), 0)

        student = next(
            u for u in payload["users"] if u["username"] == "student2"
        )
        manager_role = next(
            r for r in [1, 2, 3] if r == 2
        )

        status, payload = admin.request(
            "PUT", "/api/users", {"id": student["id"], "role_id": manager_role}
        )
        self.assertEqual(status, 200)

    def test_student_cannot_manage_users(self):
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/users")
        self.assertEqual(status, 403)

    def test_violations_visible_to_admin_only(self):
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/violations")
        self.assertEqual(status, 403)

        admin = ApiClient(self.client.base_url)
        admin.login("admin")
        status, payload = admin.request("GET", "/api/violations")
        self.assertEqual(status, 200)
        self.assertIn("violations", payload)

    def test_stats_scope_by_role(self):
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        stats = payload["stats"]
        self.assertIn("my_reserved", stats)
        self.assertIn("my_checked_in", stats)
        self.assertNotIn("violations", stats)

        admin = ApiClient(self.client.base_url)
        admin.login("admin")
        status, payload = admin.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        stats = payload["stats"]
        self.assertIn("rooms", stats)
        self.assertIn("seats", stats)
        self.assertIn("reserved", stats)
        self.assertIn("violations", stats)

    def test_health_endpoint(self):
        status, payload = self.client.request("GET", "/api/health", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")
        self.assertGreater(payload["table_count"], 0)

    def test_me_endpoint(self):
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["username"], "student1")
        self.assertIn("permissions", payload)
        self.assertIn("student:use", payload["permissions"])

    def test_reservation_rejects_past_time(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        past_time = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")

        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": past_time, "hours": 1},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_reservation_rejects_invalid_duration(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 0},
        )
        self.assertEqual(status, 400)

        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 10},
        )
        self.assertEqual(status, 400)

    def test_checkin_rejects_wrong_code(self):
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        status, payload = self.client.request("GET", "/api/reservations")
        reservation = payload["reservations"][0]

        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {"reservation_id": reservation["id"], "code": "WRONG-CODE"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_student_cannot_update_parameters(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "PUT", "/api/parameters", {"key": "max_hours", "value": "99"}
        )
        self.assertEqual(status, 403)

    def test_rooms_list(self):
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/rooms")
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["rooms"]), 0)

    def test_seat_filter_by_attributes(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "GET", "/api/seats", query={"near_window": "1", "has_power": "1"}
        )
        self.assertEqual(status, 200)
        for seat in payload["seats"]:
            self.assertEqual(seat["near_window"], 1)
            self.assertEqual(seat["has_power"], 1)

    def test_roles_list(self):
        admin = ApiClient(self.client.base_url)
        admin.login("admin")
        status, payload = admin.request("GET", "/api/roles")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["roles"]), 3)

    def test_reservation_not_found_on_cancel(self):
        self.client.login("student1")
        status, payload = self.client.request(
            "PUT", "/api/reservations", {"id": 99999}
        )
        self.assertEqual(status, 404)

    def test_register_success(self):
        status, payload = self.client.request("POST", "/api/register", {
            "username": "newuser",
            "password": "abcd1234",
            "display_name": "新同学",
            "department": "物理学院",
        })
        self.assertEqual(status, 200)
        self.assertIn("注册成功", payload["message"])

    def test_register_duplicate_username(self):
        self.client.request("POST", "/api/register", {
            "username": "dupuser",
            "password": "pass1234",
        })
        status, payload = self.client.request("POST", "/api/register", {
            "username": "dupuser",
            "password": "pass1234",
        })
        self.assertEqual(status, 409)

    def test_register_then_login(self):
        self.client.request("POST", "/api/register", {
            "username": "regtest",
            "password": "test1234",
            "display_name": "注册测试",
        })
        status, payload = self.client.request("POST", "/api/login", {
            "username": "regtest",
            "password": "test1234",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["role_name"], "学生")


if __name__ == "__main__":
    unittest.main()
