# 自习座位预约系统

> 复旦大学 2026 春季学期 · 软件过程管理课程实践

面向高校自习室的在线座位预约管理系统。学生可查询、预约、签到座位；管理员可管理自习室、座位和用户权限；系统支持自动违约处理和智能助手问答。

**技术栈：** 原生 HTML/CSS/JS + Python 标准库 HTTP Server + SQLite

**小组成员：** 梁志杰（组长）、马龙、卢中行、诸丁玮、尚俊霖、郑周锐

## 本地运行

1. 打开终端进入项目目录：

```bash
cd backend
```

2. 启动后端：

```bash
python server.py
```

3. 浏览器打开：

```
http://127.0.0.1:8000
```

## 演示账号

| 角色 | 账号 | 密码 |
|---|---|---|
| 学生 | student1 | 123456 |
| 教室管理员 | manager | 123456 |
| 系统管理员 | admin | 123456 |

## 华为云部署

### 前提条件

- 华为云 ECS（CentOS / Ubuntu 均可）
- 安全组放行 80 端口
- 已安装 Python 3.10+

### 一键部署

```bash
# 1. 上传 deploy 目录到服务器
scp -r deploy/ root@<ECS公网IP>:/opt/study-seat/

# 2. 安装 systemd 服务
sudo cp deploy/study-seat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable study-seat

# 3. 配置 Nginx 反向代理（可选）
sudo cp deploy/nginx.conf /etc/nginx/conf.d/study-seat.conf
sudo systemctl reload nginx

# 4. 执行部署
cd /opt/study-seat
bash deploy/deploy.sh
```

### 部署脚本说明

`deploy/deploy.sh` 会自动完成以下步骤：

1. 拉取最新代码（git pull）
2. 运行全部自动化测试（29个用例）
3. 测试通过后重启 systemd 服务
4. 健康检查确认服务正常

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_DIR` | `/opt/study-seat` | 应用目录 |
| `BRANCH` | `main` | Git 分支 |
| `MIMO_API_KEY` | 无 | 智能助手 API Key（可选） |

## CI/CD 流水线

使用 GitHub Actions，每次 push 和 PR 自动执行：

1. **代码检查** — flake8 检查代码质量
2. **构建验证** — Python 语法检查 + 前端资源验证
3. **自动化测试** — 29 个测试用例全覆盖
4. **自动部署** — main 分支推送后自动部署到华为云
5. **冒烟测试** — 部署后自动验证线上接口

## 运行测试

```bash
cd backend
python -m unittest discover -s . -p "test_*.py" -v
```

测试覆盖：

| 测试项 | 数量 |
|--------|------|
| 登录与鉴权 | 4 |
| RBAC 权限控制 | 5 |
| 预约业务（创建/冲突/取消/边界） | 6 |
| 签到（正确码/错误码） | 2 |
| 座位管理（CRUD/筛选） | 3 |
| 用户与角色管理 | 3 |
| 系统参数 | 2 |
| 统计接口 | 1 |
| 智能助手 | 4 |
| 健康检查 | 1 |
| **合计** | **29** |

## 主要功能

### 学生端

- 登录系统
- 查看自习室和座位
- 按关键字、自习室、靠窗、有插座、安静区筛选座位
- 选择开始时间和预约时长
- 创建预约
- 查看我的预约
- 输入教室动态编码签到
- 取消预约
- 使用智能助手查询空座和个人预约

### 管理端

- 工作台统计
- 自习室登记
- 座位登记
- 查看座位列表
- 查看预约记录
- 查看系统参数
- 系统管理员可调整参数
- 系统管理员可给用户分配角色
- 根据 RBAC 权限展示不同管理功能

### 智能助手

支持规则匹配，例如：

- 今天晚上还有空座吗
- 帮我找靠窗的座位
- 帮我找有插座的座位
- 帮我找靠窗并且有插座的座位
- 我今天定了哪里的座位

## 项目结构

```text
自习座位预约系统
├─ backend
│  ├─ server.py          后端服务、API、SQLite 建表和种子数据
│  ├─ test_server.py     自动化测试（29个用例）
│  ├─ smoke_test.py      线上冒烟测试
│  └─ study_seat.db      首次运行后自动生成
├─ frontend
│  ├─ index.html         前端页面结构
│  ├─ style.css          页面样式
│  └─ app.js             前端业务逻辑和 API 调用
├─ deploy
│  ├─ deploy.sh          华为云部署脚本
│  ├─ study-seat.service systemd 服务配置
│  └─ nginx.conf         Nginx 反向代理配置
├─ docs
│  ├─ 用户故事.md           用户故事与验收标准
│  ├─ 分工说明.md           6人分工
│  ├─ 功能说明.md           功能描述
│  ├─ 接口说明.md           API 文档
│  ├─ 代码Review记录.md     Review 记录
│  ├─ 例会记录.md           例会记录
│  ├─ 测试用例说明.md       测试用例文档
│  ├─ 预约业务逻辑说明.md   预约API与业务规则
│  ├─ 数据库与权限设计说明.md 数据库表结构与RBAC
│  ├─ 前端页面说明.md       学生端页面说明
│  ├─ 管理端页面说明.md     管理端页面说明
│  ├─ 华为云部署指南.md     部署步骤
│  ├─ PPT大纲.md           期末报告PPT内容
│  ├─ 演示视频脚本.md       5分钟视频录制脚本
│  └─ screenshots/         CI/CD 截图
├─ .github/workflows/
│  └─ ci.yml             GitHub Actions CI/CD 流水线
├─ CONTRIBUTING.md       协作规范
└─ README.md
```

## 智能助手 API 配置

后端智能助手默认使用本地规则回答。配置 `backend/config.json` 后，会优先调用 MiMo OpenAI-compatible Chat Completions API；接口失败或未配置 key 时，会自动回退到本地规则。

复制模板：

```bash
cp backend/config.example.json backend/config.json
```

然后编辑 `backend/config.json`：

```json
{
  "mimo_api_key": "你的 MiMo API Key",
  "mimo_api_url": "https://token-plan-cn.xiaomimimo.com/anthropic",
  "mimo_api_format": "anthropic",
  "mimo_model": "mimo-v2.5"
}
```

`backend/config.json` 已加入 `.gitignore`，不会提交到 GitHub。服务器上可以直接保留这个文件；如果没有配置文件，也可以继续使用 `MIMO_API_KEY`、`MIMO_API_URL`、`MIMO_API_FORMAT`、`MIMO_MODEL` 环境变量。

