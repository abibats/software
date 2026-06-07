# 代码 Review 记录

## Review #1: PR #2 - Assistant API Integration

- **日期：** 2026-05-25
- **作者：** 郑周锐
- **Reviewer：** 梁志杰、诸丁玮
- **分支：** `assistant-api-integration` → `main`

### Review 内容

本次 PR 集成了 MiMo 智能助手 API，支持通过外部大模型进行自然语言问答。

### Review 意见

1. **配置安全性（已解决）：** `config.json` 已加入 `.gitignore`，提供了 `config.example.json` 作为模板
2. **降级策略（已解决）：** API 不可用时自动降级到本地关键词匹配
3. **上下文传递（已解决）：** 助手 API 调用时包含当前可用座位和用户预约数据

### Review 结论

通过，合并到 main。

---

## Review #2: PR #4 - 用户故事与迭代计划

- **日期：** 2026-06-05
- **作者：** 梁志杰
- **Reviewer：** 马龙、尚俊霖
- **分支：** `feature/student-frontend` → `main`

### Review 内容

新增完整的用户故事文档，包含 4 个 Epic、13 个用户故事及验收标准。

### Review 意见

1. **用户故事覆盖度：** 4 个 Epic 覆盖了系统的所有核心功能
2. **验收标准完整性：** 每个用户故事都有可测试的验收标准
3. **分工映射清晰：** Feature 与 Epic 对应关系表明确了各成员的责任范围

### Review 结论

通过，合并到 main。

---

## Review #3: PR #5 - 学生端前端页面说明

- **日期：** 2026-06-05
- **作者：** 马龙
- **Reviewer：** 梁志杰、诸丁玮
- **分支：** `feature/student-frontend` → `main`

### Review 内容

学生端前端页面交互流程和组件说明。

### Review 意见

1. **筛选逻辑清晰：** 前端筛选参数与后端 API 参数一致
2. **交互流程完整：** 从登录到预约到签到的完整用户路径
3. **建议补充：** 可考虑增加错误提示的交互说明

### Review 结论

通过，合并到 main。

---

## Review #4: PR #7 - 预约业务逻辑说明

- **日期：** 2026-06-05
- **作者：** 诸丁玮
- **Reviewer：** 尚俊霖、马龙
- **分支：** `feature/reservation-backend` → `main`

### Review 内容

后端预约核心业务逻辑说明，包括座位查询、预约、签到、自动违约。

### Review 意见

1. **冲突检测逻辑：** 同一座位同一时段不可重复预约的规则清晰
2. **自动违约时间：** 15分钟未签到自动过期并记录违规
3. **建议：** 后续可考虑增加连续违约的惩罚机制

### Review 结论

通过，合并到 main。

---

## Review #5: PR #8 - 数据库与权限体系设计

- **日期：** 2026-06-05
- **作者：** 尚俊霖
- **Reviewer：** 梁志杰、诸丁玮
- **分支：** `feature/auth-backend` → `main`

### Review 内容

7 张数据库表结构和 RBAC 权限体系设计说明。

### Review 意见

1. **表结构完整：** 7 张表覆盖了所有业务实体
2. **RBAC 设计合理：** 三级角色权限划分清晰
3. **Token 鉴权：** 基于 Bearer Token 的鉴权方案简洁有效

### Review 结论

通过，合并到 main。

---

## Review #6: PR #9 - 测试用例与 CI/CD 说明

- **日期：** 2026-06-05
- **作者：** 郑周锐
- **Reviewer：** 梁志杰、诸丁玮
- **分支：** `feature/testing-devops` → `main`

### Review 内容

29 个测试用例说明、CI/CD 流水线配置、智能助手实现说明。

### Review 意见

1. **测试覆盖：** 核心功能（登录、权限、预约、签到、座位管理、智能助手）均有测试覆盖
2. **CI 流水线：** GitHub Actions 五阶段流水线（lint → build → test → deploy → smoke test）
3. **测试完整性：** 包含取消预约、座位 CRUD、权限边界、边界情况等测试用例

### Review 结论

通过，合并到 main。
