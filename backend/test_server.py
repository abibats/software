"""
Study Seat API Test Suite
该测试套件用于验证自习室座位预约系统后端 API 的各项功能，
包括用户认证、权限控制、预约逻辑、签到逻辑、AI助手交互以及系统配置等。
"""

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
    """
    HTTP 测试客户端封装类。
    用于在测试用例中方便地向本地启动的测试服务器发送 HTTP 请求，
    自动处理 JSON 序列化/反序列化以及 Bearer Token 鉴权头。
    """
    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None # 存储登录后获取的 JWT/Auth Token

    def request(self, method, path, body=None, token=True, query=None):
        """发送 HTTP 请求的核心方法"""
        # 拼接 URL 查询参数
        if query:
            path = f"{path}?{urlencode(query)}"
        data = None
        headers = {"Content-Type": "application/json"}
        
        # 将字典类型的 body 转换为 JSON 字节流
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            
        # 如果需要鉴权且当前客户端已登录(有token)，则自动携带 Authorization 头部
        if token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        req = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            # 发起请求，设置 5 秒超时
            with urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 捕获 HTTP 错误（如 400, 401, 403, 404, 500 等），并尝试解析返回的错误 JSON 信息
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                return exc.code, payload
            finally:
                exc.close()

    def login(self, username, password="123456"):
        """快捷登录方法，成功后自动将 Token 存储在实例中"""
        status, payload = self.request(
            "POST",
            "/api/login",
            {"username": username, "password": password},
            token=False, # 登录接口本身不需要 Token
        )
        if status == 200:
            self.token = payload["token"]
        return status, payload


class FakeApiResponse:
    """
    用于 Mock 第三方 API（如 AI 助手外部接口）请求的伪造响应类。
    支持上下文管理器（with 语句）和读取（read）操作，以模拟 urllib.response 的行为。
    """
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
    """自习室座位 API 单元测试主类"""
    
    def setUp(self):
        """
        每个测试用例执行前运行。
        负责隔离测试环境：备份环境变量、创建临时数据库和配置文件、启动测试用独立 HTTP 服务器。
        """
        # 1. 备份并清空与 AI 助手相关的环境变量，防止本地环境污染测试结果
        self.original_env = {
            key: os.environ.get(key)
            for key in ("MIMO_API_KEY", "MIMO_API_URL", "MIMO_MODEL", "AI_API_KEY")
        }
        for key in self.original_env:
            os.environ.pop(key, None)
            
        # 2. 创建临时目录用于存放测试数据库和配置文件，避免修改真实数据
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_db_path = server.DB_PATH
        self.original_config_path = server.CONFIG_PATH
        server.DB_PATH = Path(self.tmp.name) / "test_study_seat.db"
        server.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        
        # 3. 清理服务器内存中的 Token，并初始化测试数据库表结构
        server.TOKENS.clear()
        server.init_db()

        # 4. 在后台线程启动测试服务器，使用系统自动分配的空闲端口 ("127.0.0.1", 0)
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        
        # 5. 初始化测试客户端，指向刚启动的测试服务器地址
        host, port = self.httpd.server_address
        self.client = ApiClient(f"http://{host}:{port}")

    def tearDown(self):
        """
        每个测试用例执行后运行。
        负责清理测试环境：关闭服务器、恢复原本的文件路径和环境变量、清理临时文件。
        """
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        
        # 恢复应用状态和全局变量
        server.DB_PATH = self.original_db_path
        server.CONFIG_PATH = self.original_config_path
        server.TOKENS.clear()
        self.tmp.cleanup()
        
        # 恢复环境变量
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ================= 辅助方法 =================

    def future_hour(self):
        """生成一个未来的时间（明天早上 9 点），用于有效的座位预约测试"""
        return (datetime.now() + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )

    def active_seat_id(self):
        """请求 API 获取第一个可用（active）状态的座位 ID"""
        status, payload = self.client.request(
            "GET", "/api/seats", query={"status": "active"}
        )
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["seats"]), 0) # 确保数据库初始化时有可用座位
        return payload["seats"][0]["id"]

    # ================= 测试用例 =================

    def test_login_success_and_failure(self):
        """测试正常登录和密码错误/用户不存在等登录失败场景"""
        # 测试成功登录
        status, payload = self.client.login("student1")
        self.assertEqual(status, 200)
        self.assertIn("token", payload)
        self.assertEqual(payload["user"]["username"], "student1")

        # 测试密码错误
        bad_client = ApiClient(self.client.base_url)
        status, payload = bad_client.login("student1", "wrong-password")
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_api_requires_bearer_token(self):
        """测试受保护的 API 必须携带有效的 Bearer Token"""
        status, payload = self.client.request("GET", "/api/me", token=False)
        self.assertEqual(status, 401)
        self.assertIn("error", payload)

    def test_student_cannot_create_room_but_manager_can(self):
        """测试基于角色的访问控制 (RBAC)：学生无权创建自习室，但管理员有权创建"""
        # 学生尝试创建自习室 -> 被拒绝 (403)
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

        # 管理员尝试创建自习室 -> 成功 (200)
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

        # 验证自习室是否真被存入系统
        status, payload = manager.request("GET", "/api/rooms")
        self.assertEqual(status, 200)
        self.assertTrue(any(room["name"] == "Test Room" for room in payload["rooms"]))

    def test_reservation_rejects_overlap_for_same_seat(self):
        """测试预约系统防冲突机制：同一个座位在同一时间段内不能被重复预约"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # 第一次预约 (2小时) -> 成功
        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 2},
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        # 第二次在重叠时间预约该座位 (1小时) -> 冲突被拒绝 (409)
        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 409)
        self.assertIn("error", payload)

    def test_checkin_rejects_before_start_time(self):
        """测试签到限制：未到预约开始时间前禁止提前签到"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M") # 预约的是明天

        # 发起预约
        status, _ = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 200)

        # 获取预约记录并尝试立即签到 -> 失败 (400)
        status, payload = self.client.request("GET", "/api/reservations")
        reservation = payload["reservations"][0]

        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {"reservation_id": reservation["id"], "code": reservation["daily_code"]},
        )
        self.assertEqual(status, 400)
        self.assertIn("还未到预约开始时间", payload["error"])

    def test_checkin_success_when_start_time_reached(self):
        """测试成功签到场景：达到预约时间后提供正确的签到码可以签到"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        now = datetime.now()
        # 直接通过数据库插入一条开始时间在 5 分钟前（正在进行中）的预约记录
        start = (now - timedelta(minutes=5)).replace(second=0, microsecond=0)
        end = start + timedelta(hours=2)
        
        db = server.connect()
        db.execute(
            "INSERT INTO reservations(user_id,seat_id,start_time,end_time,status,created_at) VALUES(?,?,?,?,?,?)",
            (3, seat_id, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), "reserved", server.now_text()),
        )
        db.commit()
        db.close()

        # 请求签到 -> 成功 (200)
        status, payload = self.client.request("GET", "/api/reservations")
        reservation = payload["reservations"][0]

        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {"reservation_id": reservation["id"], "code": reservation["daily_code"]},
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

    def test_admin_can_update_parameters(self):
        """测试超级管理员 (admin) 可以修改系统全局参数（如最大预约时长）"""
        self.client.login("admin")
        
        # 修改参数 max_hours 为 3
        status, payload = self.client.request(
            "PUT", "/api/parameters", {"key": "max_hours", "value": "3"}
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        # 验证修改是否生效
        status, payload = self.client.request("GET", "/api/parameters")
        self.assertEqual(status, 200)
        max_hours = next(p for p in payload["parameters"] if p["key"] == "max_hours")
        self.assertEqual(max_hours["value"], "3")

    def test_assistant_falls_back_without_api_key(self):
        """测试 AI 助手降级机制：如果未配置 API Key，应返回降级的静态/规则回复"""
        self.client.login("student1")
        status, payload = self.client.request(
            "POST", "/api/assistant", {"message": "怎么签到"}
        )
        self.assertEqual(status, 200)
        self.assertIn("reply", payload)
        self.assertNotEqual(payload.get("source"), "api") # 回复来源不应是外部 API

    def test_assistant_uses_mimo_api_when_configured(self):
        """测试 AI 助手外部接口对接：配置环境变量后，系统应调用外部 LLM API"""
        self.client.login("student1")
        # 配置模拟的外部 AI 接口参数
        os.environ["MIMO_API_KEY"] = "test-key"
        os.environ["MIMO_API_URL"] = "https://example.test/chat/completions"
        os.environ["MIMO_MODEL"] = "mimo-v2.5"

        fake_payload = {
            "choices": [
                {"message": {"content": "可以，我已经根据当前座位数据为你筛选。"}}
            ]
        }
        
        # 使用 mock 拦截外部 HTTP 请求，返回我们预设的 fake_payload
        with patch("server.urlopen", return_value=FakeApiResponse(fake_payload)) as mocked_urlopen:
            status, payload = self.client.request(
                "POST", "/api/assistant", {"message": "帮我找一个靠窗座位"}
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "api") # 验证来源为外部 API
        self.assertEqual(payload["reply"], "可以，我已经根据当前座位数据为你筛选。")
        self.assertTrue(mocked_urlopen.called) # 确保 urllib 真的被调用了

    def test_assistant_uses_config_file_when_present(self):
        """测试系统读取配置文件：应优先读取 config.json 中的 AI 接口配置"""
        self.client.login("student1")
        # 写入临时配置文件
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
        # 验证发出请求的目标地址是配置文件里写的那个
        self.assertEqual(request.full_url, "https://example.test/from-config")

    def test_config_file_allows_utf8_bom(self):
        """测试对带有 BOM(Byte Order Mark) 的 UTF-8 配置文件的兼容性"""
        server.CONFIG_PATH.write_text(
            json.dumps({"mimo_api_key": "config-key"}),
            encoding="utf-8-sig", # 强制写入带 BOM 的 UTF-8
        )
        # 确保系统能正常读取并判断助手已配置
        self.assertTrue(server.assistant_api_configured())

    def test_assistant_supports_anthropic_token_plan_endpoint(self):
        """测试对 Anthropic (Claude) 格式 API 端点的兼容性与请求体格式适配"""
        self.client.login("student1")
        server.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "mimo_api_key": "config-key",
                    "mimo_api_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
                    "mimo_api_format": "anthropic", # 指定格式为 anthropic
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
            "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages", # 验证自动补充了 API 路径
        )
        # 验证 Anthropic 特有的请求体参数是否正确构建
        self.assertEqual(body["max_tokens"], 600)
        self.assertIn("system", body)

    def test_cancel_reservation(self):
        """测试取消预约功能（将预约状态变更为 cancelled）"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # 1. 发起预约
        status, _ = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 200)

        # 2. 获取记录，取出 id
        status, payload = self.client.request("GET", "/api/reservations")
        self.assertEqual(status, 200)
        reservation = payload["reservations"][0]

        # 3. 发送取消预约请求（使用 PUT）
        status, payload = self.client.request(
            "PUT", "/api/reservations", {"id": reservation["id"]}
        )
        self.assertEqual(status, 200)
        self.assertIn("message", payload)

        # 4. 再次获取列表，验证状态是否为 'cancelled'
        status, payload = self.client.request("GET", "/api/reservations")
        cancelled = next(
            r for r in payload["reservations"] if r["id"] == reservation["id"]
        )
        self.assertEqual(cancelled["status"], "cancelled")

    def test_reservations_filter_by_status(self):
        """测试历史预约记录能够根据状态 (status) 进行过滤筛选"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # 增加一条预约并立刻取消它
        status, _ = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        self.assertEqual(status, 200)

        status, payload = self.client.request("GET", "/api/reservations")
        reservation = payload["reservations"][0]
        status, _ = self.client.request(
            "PUT", "/api/reservations", {"id": reservation["id"]}
        )
        self.assertEqual(status, 200)

        # 使用查询参数 `status=cancelled` 获取列表
        status, payload = self.client.request(
            "GET", "/api/reservations", query={"status": "cancelled"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["reservations"]), 1)
        self.assertEqual(payload["reservations"][0]["id"], reservation["id"])

        # 测试无效的状态过滤参数应当报错
        status, payload = self.client.request(
            "GET", "/api/reservations", query={"status": "unknown"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_cancel_other_user_reservation_forbidden(self):
        """测试安全/越权机制：学生不允许取消其他人的预约"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # student1 发起预约
        self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        status, payload = self.client.request("GET", "/api/reservations")
        reservation_id = payload["reservations"][0]["id"]

        # student2 尝试取消 student1 的预约 -> 被拒绝 (403 越权)
        other = ApiClient(self.client.base_url)
        other.login("student2")
        status, payload = other.request(
            "PUT", "/api/reservations", {"id": reservation_id}
        )
        self.assertEqual(status, 403)

    def test_seat_crud(self):
        """测试管理员对座位的增、查、改 (CRUD) 操作"""
        manager = ApiClient(self.client.base_url)
        manager.login("manager")

        # 增
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

        # 查
        status, payload = manager.request(
            "GET", "/api/seats", query={"keyword": "T-99"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["seats"]), 1)
        seat = payload["seats"][0]
        self.assertEqual(seat["code"], "T-99")
        self.assertEqual(seat["near_window"], 1)
        self.assertEqual(seat["has_power"], 1)

        # 改
        status, payload = manager.request(
            "PUT",
            "/api/seats",
            {"id": seat["id"], "room_id": 1, "code": "T-99-MOD", "quiet_zone": True},
        )
        self.assertEqual(status, 200)

        # 验证修改
        status, payload = manager.request(
            "GET", "/api/seats", query={"keyword": "T-99"}
        )
        self.assertEqual(payload["seats"][0]["code"], "T-99-MOD")

    def test_student_cannot_manage_seats(self):
        """测试权限机制：普通学生无权新增座位记录"""
        self.client.login("student1")
        status, payload = self.client.request(
            "POST",
            "/api/seats",
            {"room_id": 1, "code": "HACK-01"},
        )
        self.assertEqual(status, 403)

    def test_user_role_management(self):
        """测试超级管理员 (admin) 可以修改其他用户的角色 (Role)"""
        admin = ApiClient(self.client.base_url)
        admin.login("admin")

        # 获取所有用户列表
        status, payload = admin.request("GET", "/api/users")
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["users"]), 0)

        # 找到 student2 并准备将其角色提升为 manager (role_id=2)
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
        """测试权限机制：普通学生无权获取用户列表/管理用户"""
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/users")
        self.assertEqual(status, 403)

    def test_violations_visible_to_admin_only(self):
        """测试违规记录 (violations) 对学生的不可见性和对管理员的可见性"""
        # 学生查看 -> 403
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/violations")
        self.assertEqual(status, 403)

        # 管理员查看 -> 200
        admin = ApiClient(self.client.base_url)
        admin.login("admin")
        status, payload = admin.request("GET", "/api/violations")
        self.assertEqual(status, 200)
        self.assertIn("violations", payload)

    def test_stats_scope_by_role(self):
        """测试数据统计看板 API 会根据请求者的角色返回不同范围的统计数据"""
        # 学生只能看到自己的统计数据
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/stats")
        self.assertEqual(status, 200)
        stats = payload["stats"]
        self.assertIn("my_reserved", stats)
        self.assertIn("my_checked_in", stats)
        self.assertNotIn("violations", stats) # 不应看到全校的违规总计

        # 管理员可以看到全局统计数据
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
        """测试探针接口：用于健康检查，无需登录即可返回服务和数据库的正常状态"""
        status, payload = self.client.request("GET", "/api/health", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")
        self.assertGreater(payload["table_count"], 0)

    def test_me_endpoint(self):
        """测试个人信息接口：返回当前登录用户的基础信息及权限列表"""
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["username"], "student1")
        self.assertIn("permissions", payload)
        self.assertIn("student:use", payload["permissions"])

    def test_reservation_rejects_past_time(self):
        """测试预约时间有效性：不能预约过去的时间"""
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
        """测试预约时长限制：不能低于最小值(如0)或超过最大值限制(如10小时)"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # 0小时不被允许
        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 0},
        )
        self.assertEqual(status, 400)

        # 超长预订不被允许
        status, payload = self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 10},
        )
        self.assertEqual(status, 400)

    def test_checkin_rejects_wrong_code(self):
        """测试签到机制：提供的自习室当日签到码错误时，将拒绝签到"""
        self.client.login("student1")
        seat_id = self.active_seat_id()
        start_time = self.future_hour().strftime("%Y-%m-%dT%H:%M")

        # 创建预约
        self.client.request(
            "POST",
            "/api/reservations",
            {"seat_id": seat_id, "start_time": start_time, "hours": 1},
        )
        status, payload = self.client.request("GET", "/api/reservations")
        reservation = payload["reservations"][0]

        # 提交错误的 code 进行签到 -> 报错 400
        status, payload = self.client.request(
            "POST",
            "/api/checkin",
            {"reservation_id": reservation["id"], "code": "WRONG-CODE"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_student_cannot_update_parameters(self):
        """测试权限机制：普通学生无权修改系统全局参数"""
        self.client.login("student1")
        status, payload = self.client.request(
            "PUT", "/api/parameters", {"key": "max_hours", "value": "99"}
        )
        self.assertEqual(status, 403)

    def test_rooms_list(self):
        """测试获取自习室列表"""
        self.client.login("student1")
        status, payload = self.client.request("GET", "/api/rooms")
        self.assertEqual(status, 200)
        self.assertGreater(len(payload["rooms"]), 0)

    def test_seat_filter_by_attributes(self):
        """测试获取座位列表时，根据属性(如靠窗、有电源)进行过滤的功能"""
        self.client.login("student1")
        status, payload = self.client.request(
            "GET", "/api/seats", query={"near_window": "1", "has_power": "1"}
        )
        self.assertEqual(status, 200)
        for seat in payload["seats"]:
            self.assertEqual(seat["near_window"], 1)
            self.assertEqual(seat["has_power"], 1)

    def test_roles_list(self):
        """测试管理员获取系统角色列表（至少应包含学生、管理员、超管三个角色）"""
        admin = ApiClient(self.client.base_url)
        admin.login("admin")
        status, payload = admin.request("GET", "/api/roles")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["roles"]), 3)

    def test_reservation_not_found_on_cancel(self):
        """测试取消不存在的预约时系统能正确返回 404 Not Found"""
        self.client.login("student1")
        status, payload = self.client.request(
            "PUT", "/api/reservations", {"id": 99999}
        )
        self.assertEqual(status, 404)

    def test_register_success(self):
        """测试新用户正常注册流程"""
        status, payload = self.client.request("POST", "/api/register", {
            "username": "newuser",
            "password": "abcd1234",
            "display_name": "新同学",
            "department": "物理学院",
        })
        self.assertEqual(status, 200)
        self.assertIn("注册成功", payload["message"])

    def test_register_duplicate_username(self):
        """测试注册重复用户名会被拒绝 (返回 409 Conflict)"""
        # 第一次注册
        self.client.request("POST", "/api/register", {
            "username": "dupuser",
            "password": "pass1234",
        })
        # 同样用户名第二次注册
        status, payload = self.client.request("POST", "/api/register", {
            "username": "dupuser",
            "password": "pass1234",
        })
        self.assertEqual(status, 409)

    def test_register_then_login(self):
        """测试系统连贯性：用户注册成功后可以立即使用该凭据登录，且被赋予默认的"学生"角色"""
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
    # 如果作为脚本直接运行此文件，则启动单元测试执行器
    unittest.main()
