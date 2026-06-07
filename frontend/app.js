const api = {
  token: localStorage.getItem("seat_token") || "",
  user: JSON.parse(localStorage.getItem("seat_user") || "null"),
  permissions: JSON.parse(localStorage.getItem("seat_permissions") || "[]"),
};

const state = {
  page: "dashboard",
  rooms: [],
  seats: [],
  reservations: [],
  roles: [],
  users: [],
  params: [],
  stats: {},
  chatMessages: [{ role: "bot", text: "你好，我可以帮你查空座、找靠窗/有插座座位，也可以查询你今天定了哪里。" }],
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function request(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: api.token ? `Bearer ${api.token}` : "",
      ...(options.headers || {}),
    },
  });
  const data = await res.json();
  if (res.status === 401 && api.token) {
    toast("登录已过期，请重新登录");
    logout();
    throw new Error("登录已过期");
  }
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function testHealth() {
  const status = $("healthStatus");
  status.textContent = "测试中...";
  status.className = "health-status";
  try {
    const data = await request("/api/health");
    status.textContent = `服务正常 · 数据表 ${data.table_count}`;
    status.classList.add("ok");
    toast("连接测试通过");
  } catch (err) {
    status.textContent = "连接异常";
    status.classList.add("error");
    toast(err.message);
  }
}

function can(permission) {
  return api.permissions.includes("*") || api.permissions.includes(permission);
}

function statusText(value) {
  return {
    active: "可用",
    disabled: "停用",
    reserved: "已预约",
    checked_in: "已签到",
    cancelled: "已取消",
    expired: "违约取消",
  }[value] || value;
}

function tagList(seat) {
  const tags = [];
  if (seat.near_window) tags.push("靠窗");
  if (seat.has_power) tags.push("有插座");
  if (seat.quiet_zone) tags.push("安静区");
  if (!tags.length) tags.push("普通座位");
  return tags.map((t) => `<span class="tag">${t}</span>`).join("");
}

function nextHourDate() {
  const date = new Date();
  date.setHours(date.getHours() + 1, 0, 0, 0);
  return date;
}

function datetimeLocalValue(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function login(username, password) {
  const data = await request("/api/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  api.token = data.token;
  api.user = data.user;
  api.permissions = data.permissions;
  localStorage.setItem("seat_token", api.token);
  localStorage.setItem("seat_user", JSON.stringify(api.user));
  localStorage.setItem("seat_permissions", JSON.stringify(api.permissions));
  showApp();
}

function logout() {
  localStorage.clear();
  api.token = "";
  api.user = null;
  api.permissions = [];
  state.chatMessages = [{ role: "bot", text: "你好，我可以帮你查空座、找靠窗/有插座座位，也可以查询你今天定了哪里。" }];
  $("loginView").classList.remove("hidden");
  $("mainView").classList.add("hidden");
}

function buildNav() {
  const items = [
    ["dashboard", "工作台"],
    ["student", "学生预约"],
    ["assistant", "智能助手"],
    ["records", can("violation:view") ? "预约与违约" : "我的预约"],
  ];
  if (can("room:manage") || can("seat:manage") || can("system:config") || can("user:manage")) {
    items.push(["admin", "管理后台"]);
  }
  $("nav").innerHTML = items
    .map(([id, label]) => `<button data-page="${id}" class="${state.page === id ? "active" : ""}">${label}</button>`)
    .join("");
  document.querySelectorAll("[data-page]").forEach((btn) => {
    btn.onclick = () => {
      state.page = btn.dataset.page;
      render();
    };
  });
}

async function loadData() {
  const calls = [
    request("/api/stats").then((d) => (state.stats = d.stats)),
    request("/api/rooms").then((d) => (state.rooms = d.rooms)),
    request("/api/seats").then((d) => (state.seats = d.seats)),
    request("/api/reservations").then((d) => (state.reservations = d.reservations)),
  ];
  if (can("user:manage")) calls.push(request("/api/users").then((d) => (state.users = d.users)));
  if (can("user:manage") || can("role:manage")) calls.push(request("/api/roles").then((d) => (state.roles = d.roles)));
  if (can("system:config")) calls.push(request("/api/parameters").then((d) => (state.params = d.parameters)));
  await Promise.all(calls.map((p) => p.catch((err) => console.warn(err.message))));
}

function render() {
  buildNav();
  const titles = {
    dashboard: ["Dashboard", "工作台"],
    student: ["Reservation", "学生预约"],
    assistant: ["Assistant", "智能助手"],
    admin: ["Admin", "管理后台"],
    records: ["Records", "预约与违约"],
  };
  $("pageEyebrow").textContent = titles[state.page][0];
  $("pageTitle").textContent = titles[state.page][1];
  document.querySelectorAll(".page").forEach((p) => p.classList.add("hidden"));
  $(`${state.page}Page`).classList.remove("hidden");
  if (state.page === "dashboard") renderDashboard();
  if (state.page === "student") renderStudent();
  if (state.page === "assistant") renderAssistant();
  if (state.page === "admin") renderAdmin();
  if (state.page === "records") renderRecords();
}

function renderDashboard() {
  const statItems = can("reservation:view")
    ? [
        ["开放自习室", state.stats.rooms || 0],
        ["可用座位", state.stats.seats || 0],
        ["待签到预约", state.stats.reserved || 0],
        ["已签到", state.stats.checked_in || 0],
        ["违约记录", state.stats.violations || 0],
      ]
    : [
        ["开放自习室", state.stats.rooms || 0],
        ["可用座位", state.stats.seats || 0],
        ["我的待签到", state.stats.my_reserved || 0],
        ["我的已签到", state.stats.my_checked_in || 0],
      ];
  $("dashboardPage").innerHTML = `
    <div class="grid stats">
      ${statItems.map(([label, value]) => `<div class="card stat"><span>${label}</span><strong>${value}</strong></div>`).join("")}
    </div>
    <div class="grid cards" style="margin-top:16px">
      <div class="card"><h3>学生端闭环</h3><p>查询自习室和座位，按靠窗、插座、安静区筛选，选择时间后预约，并用教室动态编码签到。</p></div>
      <div class="card"><h3>管理端闭环</h3><p>维护自习室、座位、系统参数、用户角色，查看预约和违约记录，支持 RBAC 菜单控制。</p></div>
      <div class="card"><h3>智能化支持</h3><p>聊天框支持“今天晚上还有空座吗”“帮我找靠窗座位”“我今天定了哪里”等自然语言查询。</p></div>
    </div>
  `;
}

function renderStudent() {
  const roomOptions = state.rooms.map((r) => `<option value="${r.id}">${r.name}</option>`).join("");
  $("studentPage").innerHTML = `
    <div class="toolbar">
      <label>关键字<input id="seatKeyword" placeholder="教室、楼栋、座位编号"></label>
      <label>自习室<select id="roomFilter"><option value="">全部</option>${roomOptions}</select></label>
      <label><input id="windowFilter" type="checkbox"> 靠窗</label>
      <label><input id="powerFilter" type="checkbox"> 有插座</label>
      <label><input id="quietFilter" type="checkbox"> 安静区</label>
      <button class="primary" id="searchSeatBtn">搜索座位</button>
    </div>
    <div class="grid cards" id="seatCards"></div>
  `;
  $("searchSeatBtn").onclick = searchSeats;
  drawSeatCards(state.seats.filter((s) => s.status === "active"));
}

async function searchSeats() {
  const params = new URLSearchParams();
  if ($("seatKeyword").value) params.set("keyword", $("seatKeyword").value);
  if ($("roomFilter").value) params.set("room_id", $("roomFilter").value);
  if ($("windowFilter").checked) params.set("near_window", "1");
  if ($("powerFilter").checked) params.set("has_power", "1");
  if ($("quietFilter").checked) params.set("quiet_zone", "1");
  params.set("status", "active");
  const data = await request(`/api/seats?${params}`);
  drawSeatCards(data.seats);
}

function drawSeatCards(seats) {
  const minTime = datetimeLocalValue(nextHourDate());
  $("seatCards").innerHTML = seats.map((s) => `
    <div class="card seat-card${s.occupied ? " occupied" : ""}">
      <strong>${s.room_name} · ${s.code}</strong>
      <span>${s.building} / 开放 ${s.open_time}-${s.close_time}</span>
      <div class="tags">${tagList(s)}${s.occupied ? '<span class="tag" style="background:#F2F4F7;color:#B42318;">已被预约</span>' : '<span class="tag" style="background:#D1FADF;color:#039855;">空闲</span>'}</div>
      ${s.occupied ? '<p style="color:#B42318;font-size:13px;margin:0">该座位当前时段已被预约，请选择其他座位或换一个时间段。</p>' : `
      <label>开始时间<input type="datetime-local" id="start-${s.id}" min="${minTime}" value="${minTime}" step="3600"></label>
      <label>预约时长<select id="hours-${s.id}"><option>1</option><option>2</option><option>3</option><option>4</option></select></label>
      <button class="primary" onclick="createReservation(${s.id})">预约该座位</button>`}
    </div>
  `).join("") || `<div class="card">没有找到符合条件的座位。</div>`;
}

async function createReservation(seatId) {
  const start = $(`start-${seatId}`).value;
  const hours = $(`hours-${seatId}`).value;
  if (!start) return toast("请选择开始时间");
  await request("/api/reservations", {
    method: "POST",
    body: JSON.stringify({ seat_id: seatId, start_time: start, hours }),
  });
  toast("预约成功");
  await reload();
  state.page = "records";
  render();
}

function renderRecords() {
  const rows = state.reservations.map((r) => `
    <tr>
      <td>${r.id}</td>
      <td>${r.user_name}</td>
      <td>${r.room_name}<br>${r.seat_code}</td>
      <td>${r.start_time}<br>${r.end_time}</td>
      <td>${statusText(r.status)}</td>
      <td>
        ${r.status === "reserved" ? `
          <div class="checkin-actions">
            <span class="code-hint">教室编码：${r.daily_code}</span>
            <input id="code-${r.id}" placeholder="输入教室编码">
            <button class="primary" onclick="checkin(${r.id})">签到</button>
            <button class="ghost danger" onclick="cancelReservation(${r.id})">取消</button>
          </div>
        ` : ""}
      </td>
    </tr>
  `).join("");
  $("recordsPage").innerHTML = `
    <h3>${can("reservation:view") ? "预约记录" : "我的预约记录"}</h3>
    <div class="table-wrap">
      <table>
        <thead><tr><th>ID</th><th>预约人</th><th>座位</th><th>时间</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="6">暂无预约记录</td></tr>`}</tbody>
      </table>
    </div>
    <p class="sub">演示提示：表格中显示了该教室今日动态编码，真实系统应显示在教室屏幕或二维码屏幕上。</p>
    ${can("violation:view") ? `<div id="violationBlock" class="table-wrap" style="margin-top:16px"></div>` : ""}
  `;
  if (can("violation:view")) renderViolations();
}

async function renderViolations() {
  const data = await request("/api/violations");
  $("violationBlock").innerHTML = `
    <h3>违约记录</h3>
    <table>
      <thead><tr><th>ID</th><th>学生</th><th>预约开始时间</th><th>原因</th><th>记录时间</th></tr></thead>
      <tbody>${data.violations.map((v) => `<tr><td>${v.id}</td><td>${v.user_name}</td><td>${v.start_time}</td><td>${v.reason}</td><td>${v.created_at}</td></tr>`).join("") || `<tr><td colspan="5">暂无违约记录</td></tr>`}</tbody>
    </table>
  `;
}

async function checkin(id) {
  await request("/api/checkin", {
    method: "POST",
    body: JSON.stringify({ reservation_id: id, code: $(`code-${id}`).value }),
  });
  toast("签到成功");
  await reload();
}

async function cancelReservation(id) {
  await request("/api/reservations", {
    method: "PUT",
    body: JSON.stringify({ id }),
  });
  toast("预约已取消");
  await reload();
}

function renderAssistant() {
  const messagesHtml = state.chatMessages.map((m) => `<div class="msg ${m.role}">${m.text}</div>`).join("");
  $("assistantPage").innerHTML = `
    <div class="panel">
      <div class="chat-box" id="chatBox">${messagesHtml}</div>
      <div class="chat-input">
        <input id="chatInput" placeholder="例如：今天晚上还有空座吗？">
        <button class="primary" id="sendChatBtn">发送</button>
      </div>
      <div class="demo-users" style="margin-top:12px">
        <button onclick="quickAsk('今天晚上还有空座吗')">今天晚上还有空座吗</button>
        <button onclick="quickAsk('帮我找靠窗并且有插座的座位')">靠窗有插座</button>
        <button onclick="quickAsk('我今天定了哪里的座位')">我的今日预约</button>
        <button onclick="quickAsk('推荐一个适合带电脑学习的座位')">带电脑学习</button>
        <button onclick="quickAsk('怎么签到，迟到会怎样')">签到规则</button>
        <button onclick="quickAsk('你能做什么')">帮助</button>
      </div>
    </div>
  `;
  const chatInput = $("chatInput");
  $("sendChatBtn").onclick = () => askAssistant(chatInput.value);
  chatInput.onkeydown = (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      askAssistant(chatInput.value);
    }
  };
  $("chatBox").scrollTop = $("chatBox").scrollHeight;
}

function quickAsk(text) {
  $("chatInput").value = text;
  askAssistant(text);
}

async function askAssistant(text) {
  if (!text.trim()) return;
  const box = $("chatBox");
  box.innerHTML += `<div class="msg user">${text}</div>`;
  state.chatMessages.push({ role: "user", text });
  $("chatInput").value = "";
  const data = await request("/api/assistant", {
    method: "POST",
    body: JSON.stringify({ message: text }),
  });
  box.innerHTML += `<div class="msg bot">${data.reply}</div>`;
  state.chatMessages.push({ role: "bot", text: data.reply });
  box.scrollTop = box.scrollHeight;
}

function renderAdmin() {
  $("adminPage").innerHTML = `
    <div class="split">
      <div class="panel">
        <h3>新增自习室</h3>
        <div class="form-grid">
          <label>名称<input id="roomName" value="临时开放自习室"></label>
          <label>楼栋<input id="roomBuilding" value="第二教学楼"></label>
          <label>开放院系<input id="roomDept" value="全校"></label>
          <label>开放时间<input id="roomOpen" value="07:00"></label>
          <label>关闭时间<input id="roomClose" value="22:00"></label>
          <label>动态编码<input id="roomCode" value="TEMP01"></label>
          <button class="primary" id="addRoomBtn">添加自习室</button>
        </div>
        <h3>新增座位</h3>
        <div class="form-grid">
          <label>所属自习室<select id="seatRoom">${state.rooms.map((r) => `<option value="${r.id}">${r.name}</option>`).join("")}</select></label>
          <label>座位编号<input id="seatCode" value="T-01"></label>
          <label><input id="seatWindow" type="checkbox"> 靠窗</label>
          <label><input id="seatPower" type="checkbox" checked> 有插座</label>
          <label><input id="seatQuiet" type="checkbox"> 安静区</label>
          <button class="primary" id="addSeatBtn">添加座位</button>
        </div>
      </div>
      <div class="grid">
        ${renderAdminTables()}
      </div>
    </div>
  `;
  $("addRoomBtn").onclick = addRoom;
  $("addSeatBtn").onclick = addSeat;
}

function renderAdminTables() {
  const roomTable = `
    <div class="table-wrap"><table>
      <thead><tr><th>ID</th><th>自习室</th><th>楼栋</th><th>院系</th><th>时间</th><th>编码</th></tr></thead>
      <tbody>${state.rooms.map((r) => `<tr><td>${r.id}</td><td>${r.name}</td><td>${r.building}</td><td>${r.department}</td><td>${r.open_time}-${r.close_time}</td><td>${r.daily_code}</td></tr>`).join("")}</tbody>
    </table></div>`;
  const seatTable = `
    <div class="table-wrap"><table>
      <thead><tr><th>ID</th><th>座位</th><th>自习室</th><th>标签</th><th>状态</th></tr></thead>
      <tbody>${state.seats.slice(0, 30).map((s) => `<tr><td>${s.id}</td><td>${s.code}</td><td>${s.room_name}</td><td><div class="tags">${tagList(s)}</div></td><td>${statusText(s.status)}</td></tr>`).join("")}</tbody>
    </table></div>`;
  const paramTable = can("system:config") ? `
    <div class="table-wrap"><table>
      <thead><tr><th>参数</th><th>值</th><th>操作</th></tr></thead>
      <tbody>${state.params.map((p) => `<tr><td>${p.label}</td><td><input id="param-${p.key}" value="${p.value}"></td><td><button class="ghost" onclick="saveParam('${p.key}')">保存</button></td></tr>`).join("")}</tbody>
    </table></div>` : "";
  const userTable = can("user:manage") ? `
    <div class="table-wrap"><table>
      <thead><tr><th>用户</th><th>姓名</th><th>院系</th><th>角色</th><th>调整</th></tr></thead>
      <tbody>${state.users.map((u) => `<tr><td>${u.username}</td><td>${u.display_name}</td><td>${u.department}</td><td>${u.role_name}</td><td><select id="role-${u.id}">${state.roles.map((r) => `<option value="${r.id}" ${r.id === u.role_id ? "selected" : ""}>${r.name}</option>`).join("")}</select> <button class="ghost" onclick="saveUserRole(${u.id})">保存</button></td></tr>`).join("")}</tbody>
    </table></div>` : "";
  return roomTable + seatTable + paramTable + userTable;
}

async function addRoom() {
  await request("/api/rooms", {
    method: "POST",
    body: JSON.stringify({
      name: $("roomName").value,
      building: $("roomBuilding").value,
      department: $("roomDept").value,
      open_time: $("roomOpen").value,
      close_time: $("roomClose").value,
      daily_code: $("roomCode").value,
    }),
  });
  toast("自习室已添加");
  await reload();
}

async function addSeat() {
  await request("/api/seats", {
    method: "POST",
    body: JSON.stringify({
      room_id: $("seatRoom").value,
      code: $("seatCode").value,
      near_window: $("seatWindow").checked,
      has_power: $("seatPower").checked,
      quiet_zone: $("seatQuiet").checked,
    }),
  });
  toast("座位已添加");
  await reload();
}

async function saveParam(key) {
  await request("/api/parameters", {
    method: "PUT",
    body: JSON.stringify({ key, value: $(`param-${key}`).value }),
  });
  toast("参数已保存");
  await reload();
}

async function saveUserRole(id) {
  await request("/api/users", {
    method: "PUT",
    body: JSON.stringify({ id, role_id: $(`role-${id}`).value }),
  });
  toast("角色已保存");
  await reload();
}

async function reload() {
  await loadData();
  render();
}

async function showApp() {
  $("loginView").classList.add("hidden");
  $("mainView").classList.remove("hidden");
  $("userMeta").textContent = `${api.user.display_name} / ${api.user.role_name}`;
  await reload();
}

$("loginForm").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await login($("username").value, $("password").value);
  } catch (err) {
    toast(err.message);
  }
};

$("toRegister").onclick = (e) => {
  e.preventDefault();
  $("loginForm").classList.add("hidden");
  $("registerForm").classList.remove("hidden");
};

$("toLogin").onclick = (e) => {
  e.preventDefault();
  $("registerForm").classList.add("hidden");
  $("loginForm").classList.remove("hidden");
};

$("registerForm").onsubmit = async (event) => {
  event.preventDefault();
  try {
    const body = {
      username: $("regUsername").value,
      password: $("regPassword").value,
      display_name: $("regDisplayName").value,
      department: $("regDepartment").value,
    };
    await request("/api/register", { method: "POST", body: JSON.stringify(body) });
    toast("注册成功，请登录");
    $("registerForm").classList.add("hidden");
    $("loginForm").classList.remove("hidden");
    $("username").value = body.username;
    $("password").value = "";
    $("password").focus();
  } catch (err) {
    toast(err.message);
  }
};

document.querySelectorAll("[data-user]").forEach((btn) => {
  btn.onclick = () => {
    $("username").value = btn.dataset.user;
    $("password").value = "123456";
  };
});

$("logoutBtn").onclick = logout;
$("refreshBtn").onclick = () => reload().then(() => toast("数据已刷新"));
$("healthBtn").onclick = testHealth;

window.createReservation = createReservation;
window.checkin = checkin;
window.cancelReservation = cancelReservation;
window.quickAsk = quickAsk;
window.saveParam = saveParam;
window.saveUserRole = saveUserRole;

if (api.token && api.user) {
  showApp().catch(() => logout());
}
