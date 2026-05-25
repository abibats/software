from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import mimetypes
import secrets
import sqlite3
from datetime import datetime, timedelta, date
import re

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DB_PATH = BASE_DIR / "study_seat.db"
TOKENS = {}
STARTED_AT = datetime.now()


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text():
    return date.today().isoformat()


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    with connect() as db:
        db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                permissions TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                display_name TEXT NOT NULL,
                department TEXT NOT NULL,
                role_id INTEGER NOT NULL REFERENCES roles(id)
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                building TEXT NOT NULL,
                department TEXT NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                daily_code TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                code TEXT NOT NULL,
                near_window INTEGER NOT NULL DEFAULT 0,
                has_power INTEGER NOT NULL DEFAULT 0,
                quiet_zone INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                UNIQUE(room_id, code)
            );
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                seat_id INTEGER NOT NULL REFERENCES seats(id),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                status TEXT NOT NULL,
                checked_in_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                reservation_id INTEGER NOT NULL REFERENCES reservations(id),
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS parameters (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                label TEXT NOT NULL
            );
            """
        )
        role_count = db.execute("SELECT COUNT(*) c FROM roles").fetchone()["c"]
        if role_count:
            return

        db.execute(
            "INSERT INTO roles(name, permissions) VALUES(?, ?)",
            ("系统管理员", json.dumps(["*"], ensure_ascii=False)),
        )
        db.execute(
            "INSERT INTO roles(name, permissions) VALUES(?, ?)",
            (
                "教室管理员",
                json.dumps(
                    [
                        "room:manage",
                        "seat:manage",
                        "reservation:view",
                        "reservation:manage",
                        "violation:view",
                    ],
                    ensure_ascii=False,
                ),
            ),
        )
        db.execute(
            "INSERT INTO roles(name, permissions) VALUES(?, ?)",
            ("学生", json.dumps(["student:use"], ensure_ascii=False)),
        )
        admin_role = db.execute("SELECT id FROM roles WHERE name='系统管理员'").fetchone()["id"]
        manager_role = db.execute("SELECT id FROM roles WHERE name='教室管理员'").fetchone()["id"]
        student_role = db.execute("SELECT id FROM roles WHERE name='学生'").fetchone()["id"]
        users = [
            ("admin", "123456", "系统管理员", "信息中心", admin_role),
            ("manager", "123456", "李老师", "图书馆", manager_role),
            ("student1", "123456", "张同学", "计算机学院", student_role),
            ("student2", "123456", "王同学", "软件学院", student_role),
        ]
        db.executemany(
            "INSERT INTO users(username,password,display_name,department,role_id) VALUES(?,?,?,?,?)",
            users,
        )
        db.executemany(
            "INSERT INTO parameters(key,value,label) VALUES(?,?,?)",
            [
                ("max_hours", "4", "单次最大预约小时数"),
                ("remind_before_minutes", "15", "预约前提醒分钟数"),
                ("late_remind_minutes", "10", "迟到提醒分钟数"),
                ("auto_cancel_minutes", "15", "自动取消分钟数"),
            ],
        )
        rooms = [
            ("图书馆一楼自习室", "图书馆", "全校", "07:00", "22:00", "active", "LIB101"),
            ("教学楼 A201", "第一教学楼", "全校", "07:00", "22:00", "active", "A201"),
            ("计算机学院 305", "实验楼", "计算机学院", "08:00", "23:00", "active", "CS305"),
        ]
        db.executemany(
            "INSERT INTO rooms(name,building,department,open_time,close_time,status,daily_code) VALUES(?,?,?,?,?,?,?)",
            rooms,
        )
        room_ids = [r["id"] for r in db.execute("SELECT id FROM rooms ORDER BY id").fetchall()]
        seat_rows = []
        for index, room_id in enumerate(room_ids):
            for i in range(1, 17):
                seat_rows.append(
                    (
                        room_id,
                        f"{index + 1}-{i:02d}",
                        1 if i in (1, 2, 15, 16) else 0,
                        1 if i % 3 == 0 or i in (4, 8, 12, 16) else 0,
                        1 if i <= 8 else 0,
                        "active",
                    )
                )
        db.executemany(
            "INSERT INTO seats(room_id,code,near_window,has_power,quiet_zone,status) VALUES(?,?,?,?,?,?)",
            seat_rows,
        )


def user_from_token(headers):
    auth = headers.get("Authorization", "")
    token = auth.replace("Bearer ", "", 1).strip()
    user_id = TOKENS.get(token)
    if not user_id:
        return None
    with connect() as db:
        user = db.execute(
            """
            SELECT u.*, r.name role_name, r.permissions
            FROM users u JOIN roles r ON u.role_id = r.id
            WHERE u.id=?
            """,
            (user_id,),
        ).fetchone()
        return dict(user) if user else None


def has_perm(user, perm):
    if not user:
        return False
    perms = json.loads(user["permissions"])
    return "*" in perms or perm in perms


def reservation_projection_sql():
    return """
        SELECT rv.*, u.display_name user_name, u.username, s.code seat_code,
               r.name room_name, r.building, r.daily_code
        FROM reservations rv
        JOIN users u ON rv.user_id = u.id
        JOIN seats s ON rv.seat_id = s.id
        JOIN rooms r ON s.room_id = r.id
    """


def auto_expire():
    limit = datetime.now() - timedelta(minutes=15)
    with connect() as db:
        expired = rows(
            db.execute(
                "SELECT * FROM reservations WHERE status='reserved' AND start_time < ?",
                (limit.strftime("%Y-%m-%d %H:%M:%S"),),
            )
        )
        for rv in expired:
            db.execute("UPDATE reservations SET status='expired' WHERE id=?", (rv["id"],))
            exists = db.execute(
                "SELECT id FROM violations WHERE reservation_id=?", (rv["id"],)
            ).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO violations(user_id,reservation_id,reason,created_at) VALUES(?,?,?,?)",
                    (rv["user_id"], rv["id"], "预约开始15分钟后未签到，系统自动取消", now_text()),
                )


class Handler(BaseHTTPRequestHandler):
    server_version = "StudySeatServer/1.0"

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        auto_expire()
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, parse_qs(parsed.query))
        else:
            self.serve_static(parsed.path)

    def do_POST(self):
        auto_expire()
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, parse_qs(parsed.query))

    def do_PUT(self):
        auto_expire()
        parsed = urlparse(self.path)
        self.handle_api("PUT", parsed.path, parse_qs(parsed.query))

    def do_DELETE(self):
        auto_expire()
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, parse_qs(parsed.query))

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def serve_static(self, path):
        target = FRONTEND_DIR / ("index.html" if path == "/" else path.lstrip("/"))
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def require_user(self):
        user = user_from_token(self.headers)
        if not user:
            self.send_json({"error": "请先登录"}, 401)
            return None
        return user

    def handle_api(self, method, path, query):
        try:
            if path == "/api/health" and method == "GET":
                return self.health()
            if path == "/api/login" and method == "POST":
                return self.login()
            user = self.require_user()
            if not user:
                return
            if path == "/api/me":
                return self.send_json({"user": self.public_user(user), "permissions": json.loads(user["permissions"])})
            if path == "/api/rooms":
                return self.rooms(method, user)
            if path == "/api/seats":
                return self.seats(method, user, query)
            if path == "/api/reservations":
                return self.reservations(method, user, query)
            if path == "/api/checkin" and method == "POST":
                return self.checkin(user)
            if path == "/api/violations":
                return self.violations(user)
            if path == "/api/stats":
                return self.stats(user)
            if path == "/api/users":
                return self.users(method, user)
            if path == "/api/roles":
                return self.roles(method, user)
            if path == "/api/parameters":
                return self.parameters(method, user)
            if path == "/api/assistant" and method == "POST":
                return self.assistant(user)
            self.send_json({"error": "接口不存在"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def health(self):
        with connect() as db:
            db.execute("SELECT 1").fetchone()
            table_count = db.execute("SELECT COUNT(*) c FROM sqlite_master WHERE type='table'").fetchone()["c"]
        self.send_json(
            {
                "status": "ok",
                "database": "ok",
                "table_count": table_count,
                "server_time": now_text(),
                "started_at": STARTED_AT.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    def public_user(self, user):
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "department": user["department"],
            "role_name": user["role_name"],
        }

    def login(self):
        data = self.read_json()
        with connect() as db:
            user = db.execute(
                """
                SELECT u.*, r.name role_name, r.permissions
                FROM users u JOIN roles r ON u.role_id=r.id
                WHERE username=? AND password=?
                """,
                (data.get("username"), data.get("password")),
            ).fetchone()
        if not user:
            return self.send_json({"error": "账号或密码错误"}, 401)
        token = secrets.token_hex(24)
        TOKENS[token] = user["id"]
        user = dict(user)
        self.send_json({"token": token, "user": self.public_user(user), "permissions": json.loads(user["permissions"])})

    def rooms(self, method, user):
        data = self.read_json() if method in ("POST", "PUT") else {}
        with connect() as db:
            if method == "GET":
                result = rows(db.execute("SELECT * FROM rooms ORDER BY id DESC"))
                return self.send_json({"rooms": result})
            if not has_perm(user, "room:manage"):
                return self.send_json({"error": "没有教室管理权限"}, 403)
            if method == "POST":
                db.execute(
                    "INSERT INTO rooms(name,building,department,open_time,close_time,status,daily_code) VALUES(?,?,?,?,?,?,?)",
                    (
                        data["name"],
                        data["building"],
                        data.get("department", "全校"),
                        data.get("open_time", "07:00"),
                        data.get("close_time", "22:00"),
                        data.get("status", "active"),
                        data.get("daily_code", secrets.token_hex(3).upper()),
                    ),
                )
                return self.send_json({"message": "自习室已添加"})
            if method == "PUT":
                db.execute(
                    "UPDATE rooms SET name=?,building=?,department=?,open_time=?,close_time=?,status=?,daily_code=? WHERE id=?",
                    (
                        data["name"],
                        data["building"],
                        data.get("department", "全校"),
                        data.get("open_time", "07:00"),
                        data.get("close_time", "22:00"),
                        data.get("status", "active"),
                        data.get("daily_code", ""),
                        data["id"],
                    ),
                )
                return self.send_json({"message": "自习室已更新"})
            return self.send_json({"error": "不支持的方法"}, 405)

    def seats(self, method, user, query):
        data = self.read_json() if method in ("POST", "PUT") else {}
        with connect() as db:
            if method == "GET":
                sql = """
                    SELECT s.*, r.name room_name, r.building, r.department, r.open_time, r.close_time
                    FROM seats s JOIN rooms r ON s.room_id=r.id WHERE 1=1
                """
                params = []
                if query.get("room_id"):
                    sql += " AND s.room_id=?"
                    params.append(query["room_id"][0])
                if query.get("keyword"):
                    sql += " AND (s.code LIKE ? OR r.name LIKE ? OR r.building LIKE ?)"
                    kw = f"%{query['keyword'][0]}%"
                    params += [kw, kw, kw]
                for key in ("near_window", "has_power", "quiet_zone"):
                    if query.get(key) == ["1"]:
                        sql += f" AND s.{key}=1"
                if query.get("status"):
                    sql += " AND s.status=?"
                    params.append(query["status"][0])
                sql += " ORDER BY r.id, s.code"
                return self.send_json({"seats": rows(db.execute(sql, params))})
            if not has_perm(user, "seat:manage"):
                return self.send_json({"error": "没有座位管理权限"}, 403)
            if method == "POST":
                db.execute(
                    "INSERT INTO seats(room_id,code,near_window,has_power,quiet_zone,status) VALUES(?,?,?,?,?,?)",
                    (
                        data["room_id"],
                        data["code"],
                        int(bool(data.get("near_window"))),
                        int(bool(data.get("has_power"))),
                        int(bool(data.get("quiet_zone"))),
                        data.get("status", "active"),
                    ),
                )
                return self.send_json({"message": "座位已添加"})
            if method == "PUT":
                db.execute(
                    "UPDATE seats SET room_id=?,code=?,near_window=?,has_power=?,quiet_zone=?,status=? WHERE id=?",
                    (
                        data["room_id"],
                        data["code"],
                        int(bool(data.get("near_window"))),
                        int(bool(data.get("has_power"))),
                        int(bool(data.get("quiet_zone"))),
                        data.get("status", "active"),
                        data["id"],
                    ),
                )
                return self.send_json({"message": "座位已更新"})

    def reservations(self, method, user, query):
        data = self.read_json() if method in ("POST", "PUT") else {}
        with connect() as db:
            if method == "GET":
                base = reservation_projection_sql()
                params = []
                if not has_perm(user, "reservation:view"):
                    base += " WHERE rv.user_id=?"
                    params.append(user["id"])
                elif query.get("mine") == ["1"]:
                    base += " WHERE rv.user_id=?"
                    params.append(user["id"])
                base += " ORDER BY rv.start_time DESC"
                return self.send_json({"reservations": rows(db.execute(base, params))})
            if method == "POST":
                target_user_id = data.get("user_id") or user["id"]
                if target_user_id != user["id"] and not has_perm(user, "reservation:manage"):
                    return self.send_json({"error": "没有代预约权限"}, 403)
                start = datetime.strptime(data["start_time"], "%Y-%m-%dT%H:%M")
                hours = int(data["hours"])
                max_hours = int(db.execute("SELECT value FROM parameters WHERE key='max_hours'").fetchone()["value"])
                if start <= datetime.now():
                    return self.send_json({"error": "不能预约过去的时间，请选择当前时间之后的整点"}, 400)
                if start.minute != 0:
                    return self.send_json({"error": "预约开始时间必须为整点"}, 400)
                if hours < 1 or hours > max_hours:
                    return self.send_json({"error": f"单次预约必须为1到{max_hours}小时"}, 400)
                end = start + timedelta(hours=hours)
                overlap = db.execute(
                    """
                    SELECT id FROM reservations
                    WHERE seat_id=? AND status IN ('reserved','checked_in')
                    AND NOT(end_time<=? OR start_time>=?)
                    """,
                    (data["seat_id"], start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
                ).fetchone()
                if overlap:
                    return self.send_json({"error": "该座位在所选时间已被预约"}, 409)
                seat = db.execute("SELECT status FROM seats WHERE id=?", (data["seat_id"],)).fetchone()
                if not seat or seat["status"] != "active":
                    return self.send_json({"error": "座位不可用"}, 400)
                db.execute(
                    "INSERT INTO reservations(user_id,seat_id,start_time,end_time,status,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        target_user_id,
                        data["seat_id"],
                        start.strftime("%Y-%m-%d %H:%M:%S"),
                        end.strftime("%Y-%m-%d %H:%M:%S"),
                        "reserved",
                        now_text(),
                    ),
                )
                return self.send_json({"message": "预约成功"})
            if method == "PUT":
                rv = db.execute("SELECT * FROM reservations WHERE id=?", (data["id"],)).fetchone()
                if not rv:
                    return self.send_json({"error": "预约不存在"}, 404)
                if rv["user_id"] != user["id"] and not has_perm(user, "reservation:manage"):
                    return self.send_json({"error": "没有取消该预约的权限"}, 403)
                db.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (data["id"],))
                return self.send_json({"message": "预约已取消"})

    def checkin(self, user):
        data = self.read_json()
        with connect() as db:
            rv = db.execute(
                reservation_projection_sql() + " WHERE rv.id=?",
                (data["reservation_id"],),
            ).fetchone()
            if not rv:
                return self.send_json({"error": "预约不存在"}, 404)
            rv = dict(rv)
            if rv["user_id"] != user["id"] and not has_perm(user, "reservation:manage"):
                return self.send_json({"error": "没有签到权限"}, 403)
            if data.get("code", "").strip().upper() != rv["daily_code"].upper():
                return self.send_json({"error": "教室动态编码错误"}, 400)
            db.execute(
                "UPDATE reservations SET status='checked_in', checked_in_at=? WHERE id=?",
                (now_text(), rv["id"]),
            )
            return self.send_json({"message": "签到成功"})

    def violations(self, user):
        if not has_perm(user, "violation:view"):
            return self.send_json({"error": "没有查看违约记录权限"}, 403)
        with connect() as db:
            result = rows(
                db.execute(
                    """
                    SELECT v.*, u.display_name user_name, rv.start_time
                    FROM violations v
                    JOIN users u ON v.user_id=u.id
                    JOIN reservations rv ON v.reservation_id=rv.id
                    ORDER BY v.created_at DESC
                    """
                )
            )
        self.send_json({"violations": result})

    def stats(self, user):
        with connect() as db:
            result = {
                "rooms": db.execute("SELECT COUNT(*) c FROM rooms WHERE status='active'").fetchone()["c"],
                "seats": db.execute("SELECT COUNT(*) c FROM seats WHERE status='active'").fetchone()["c"],
            }
            if has_perm(user, "reservation:view"):
                result.update(
                    {
                        "reserved": db.execute("SELECT COUNT(*) c FROM reservations WHERE status='reserved'").fetchone()["c"],
                        "checked_in": db.execute("SELECT COUNT(*) c FROM reservations WHERE status='checked_in'").fetchone()["c"],
                        "violations": db.execute("SELECT COUNT(*) c FROM violations").fetchone()["c"],
                    }
                )
            else:
                result.update(
                    {
                        "my_reserved": db.execute(
                            "SELECT COUNT(*) c FROM reservations WHERE user_id=? AND status='reserved'",
                            (user["id"],),
                        ).fetchone()["c"],
                        "my_checked_in": db.execute(
                            "SELECT COUNT(*) c FROM reservations WHERE user_id=? AND status='checked_in'",
                            (user["id"],),
                        ).fetchone()["c"],
                    }
                )
        self.send_json({"stats": result})

    def users(self, method, user):
        if not has_perm(user, "user:manage"):
            return self.send_json({"error": "没有用户管理权限"}, 403)
        data = self.read_json() if method == "PUT" else {}
        with connect() as db:
            if method == "GET":
                return self.send_json(
                    {
                        "users": rows(
                            db.execute(
                                "SELECT u.id,u.username,u.display_name,u.department,u.role_id,r.name role_name FROM users u JOIN roles r ON u.role_id=r.id ORDER BY u.id"
                            )
                        )
                    }
                )
            if method == "PUT":
                db.execute("UPDATE users SET role_id=? WHERE id=?", (data["role_id"], data["id"]))
                return self.send_json({"message": "用户角色已更新"})

    def roles(self, method, user):
        if not has_perm(user, "role:manage") and not has_perm(user, "user:manage"):
            return self.send_json({"error": "没有角色管理权限"}, 403)
        with connect() as db:
            return self.send_json({"roles": rows(db.execute("SELECT * FROM roles ORDER BY id"))})

    def parameters(self, method, user):
        data = self.read_json() if method == "PUT" else {}
        with connect() as db:
            if method == "GET":
                return self.send_json({"parameters": rows(db.execute("SELECT * FROM parameters ORDER BY key"))})
            if not has_perm(user, "system:config"):
                return self.send_json({"error": "没有系统参数权限"}, 403)
            db.execute("UPDATE parameters SET value=? WHERE key=?", (data["value"], data["key"]))
            return self.send_json({"message": "参数已更新"})

    def assistant(self, user):
        data = self.read_json()
        text = data.get("message", "").strip()
        with connect() as db:
            if not text:
                return self.send_json({"reply": "你可以问我：今晚还有空座吗、帮我找靠窗有插座的座位、我今天预约了哪里。"})
            if any(word in text for word in ["帮助", "怎么用", "你能做什么", "功能"]):
                return self.send_json(
                    {
                        "reply": "\n".join(
                            [
                                "我可以完成这些任务：",
                                "1. 查询空座：今天晚上还有空座吗？",
                                "2. 条件找座：帮我找靠窗、有插座、安静区的座位。",
                                "3. 查询预约：我今天预约了哪里？",
                                "4. 提醒规则：怎么签到？迟到会怎样？",
                                "5. 预约建议：推荐一个适合带电脑学习的座位。",
                            ]
                        )
                    }
                )
            if any(word in text for word in ["签到", "到场", "验证码", "编码", "二维码"]):
                return self.send_json(
                    {
                        "reply": "签到规则：到达自习室后，在“预约与违约”页面输入教室屏幕显示的动态编码。预约开始10分钟后未签到会提醒，15分钟后仍未签到会自动取消并记录一次违约。"
                    }
                )
            if any(word in text for word in ["违约", "迟到", "超时", "没去"]):
                return self.send_json(
                    {
                        "reply": "违约规则：预约开始后15分钟仍未签到，系统会自动取消预约、释放座位，并生成违约记录。你可以提前在预约记录里取消预约，避免违约。"
                    }
                )
            if "我" in text and ("定" in text or "预约" in text or "订" in text):
                day_filter = today_text()
                if "明天" in text:
                    day_filter = (date.today() + timedelta(days=1)).isoformat()
                result = rows(
                    db.execute(
                        reservation_projection_sql()
                        + " WHERE rv.user_id=? AND date(rv.start_time)=? ORDER BY rv.start_time",
                        (user["id"], day_filter),
                    )
                )
                title = "你明天的预约如下：" if "明天" in text else "你今天的预约如下："
                return self.send_json({"reply": render_reservation_answer(result, title)})

            intent_find_seat = any(
                word in text
                for word in ["空座", "座位", "找座", "推荐", "学习", "自习", "电脑", "充电", "靠窗", "安静", "今晚", "今天", "明天"]
            )
            if intent_find_seat:
                query = extract_assistant_filters(text)
                time_window = extract_time_window(text)
                sql = """
                    SELECT s.*, r.name room_name, r.building, r.open_time, r.close_time
                    FROM seats s JOIN rooms r ON s.room_id=r.id
                    WHERE s.status='active' AND r.status='active'
                """
                params = []
                for key, value in query.items():
                    sql += f" AND s.{key}=?"
                    params.append(value)
                if user["department"]:
                    sql += " AND (r.department='全校' OR r.department=?)"
                    params.append(user["department"])
                sql += " ORDER BY r.id, s.code LIMIT 16"
                candidates = rows(db.execute(sql, params))
                available = []
                for seat in candidates:
                    if time_window and not is_seat_available(db, seat["id"], time_window[0], time_window[1]):
                        continue
                    available.append(seat)
                    if len(available) >= 8:
                        break
                return self.send_json({"reply": render_assistant_seat_answer(available, query, time_window)})

            if any(word in text for word in ["取消", "不去了"]):
                return self.send_json({"reply": "取消预约请进入“预约与违约”页面，在待签到预约右侧点击“取消”。只有未签到的预约可以直接取消。"})
            return self.send_json({"reply": "我没有完全理解。你可以试试：今晚还有空座吗、帮我找靠窗有插座的座位、我今天预约了哪里、怎么签到。"})


def extract_assistant_filters(text):
    query = {}
    if "靠窗" in text or "窗边" in text or "窗" in text:
        query["near_window"] = 1
    if any(word in text for word in ["插座", "充电", "电源", "电脑", "笔记本"]):
        query["has_power"] = 1
    if any(word in text for word in ["安静", "静音", "少人", "专注"]):
        query["quiet_zone"] = 1
    if "推荐" in text and any(word in text for word in ["电脑", "笔记本", "资料"]):
        query["has_power"] = 1
    return query


def extract_time_window(text):
    target = date.today()
    if "明天" in text:
        target = date.today() + timedelta(days=1)
    start_hour = None
    end_hour = None
    if any(word in text for word in ["今晚", "晚上"]):
        start_hour, end_hour = 18, 22
    elif any(word in text for word in ["下午"]):
        start_hour, end_hour = 14, 18
    elif any(word in text for word in ["上午", "早上"]):
        start_hour, end_hour = 8, 12
    numbers = [int(n) for n in re.findall(r"(\d{1,2})\s*[点:时]", text)]
    if len(numbers) >= 2:
        start_hour, end_hour = normalize_hour(numbers[0], text), normalize_hour(numbers[1], text)
    elif len(numbers) == 1:
        start_hour = normalize_hour(numbers[0], text)
        end_hour = min(start_hour + 2, 23)
    if start_hour is None:
        return None
    start = datetime.combine(target, datetime.min.time()).replace(hour=start_hour)
    end = datetime.combine(target, datetime.min.time()).replace(hour=end_hour)
    if end <= start:
        end = start + timedelta(hours=2)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def normalize_hour(hour, text):
    if hour <= 12 and any(word in text for word in ["下午", "晚上", "今晚"]):
        return hour + 12
    return hour


def is_seat_available(db, seat_id, start, end):
    overlap = db.execute(
        """
        SELECT id FROM reservations
        WHERE seat_id=? AND status IN ('reserved','checked_in')
        AND NOT(end_time<=? OR start_time>=?)
        """,
        (seat_id, start, end),
    ).fetchone()
    return overlap is None


def render_seat_answer(seats):
    if not seats:
        return "暂时没有找到符合条件的可用座位。"
    lines = ["找到以下可预约座位："]
    for s in seats:
        tags = []
        if s["near_window"]:
            tags.append("靠窗")
        if s["has_power"]:
            tags.append("有插座")
        if s["quiet_zone"]:
            tags.append("安静区")
        lines.append(f"{s['room_name']} {s['seat_code'] if 'seat_code' in s else s['code']}（{s['building']}，{'/'.join(tags) or '普通座'}）")
    return "\n".join(lines)


def render_assistant_seat_answer(seats, filters, time_window):
    if not seats:
        return "暂时没有找到符合条件的可用座位。你可以放宽条件，例如去掉靠窗或插座要求，或者换一个时间段。"
    labels = []
    if filters.get("near_window"):
        labels.append("靠窗")
    if filters.get("has_power"):
        labels.append("有插座")
    if filters.get("quiet_zone"):
        labels.append("安静区")
    if time_window:
        labels.append(f"{time_window[0][5:16]} 到 {time_window[1][11:16]}")
    title = "按你的条件找到这些座位：" if labels else "当前可推荐的座位如下："
    lines = [title]
    if labels:
        lines.append("条件：" + "、".join(labels))
    for s in seats:
        tags = []
        if s["near_window"]:
            tags.append("靠窗")
        if s["has_power"]:
            tags.append("有插座")
        if s["quiet_zone"]:
            tags.append("安静区")
        lines.append(f"- {s['room_name']} {s['code']}（{s['building']}，{'/'.join(tags) or '普通座'}，开放 {s['open_time']}-{s['close_time']}）")
    lines.append("需要预约时，请到“学生预约”页面选择该座位和时间。")
    return "\n".join(lines)


def render_reservation_answer(items, prefix):
    if not items:
        return "今天没有查询到你的有效预约。"
    lines = [prefix]
    for r in items:
        lines.append(f"{r['room_name']} {r['seat_code']}，{r['start_time']} 到 {r['end_time']}，状态：{r['status']}")
    return "\n".join(lines)


if __name__ == "__main__":
    init_db()
    host = "127.0.0.1"
    port = 8000
    print(f"自习座位预约系统已启动：http://{host}:{port}")
    print("演示账号：admin/123456, manager/123456, student1/123456")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
