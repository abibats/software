# 协作规范 - PR 工作流指南

## 分支命名规范

每位成员使用独立的 feature 分支进行开发：

| 分支名 | 职责范围 |
|--------|----------|
| `feature/student-frontend` | 学生端前端 |
| `feature/admin-frontend` | 管理端前端 |
| `feature/reservation-backend` | 后端预约业务 |
| `feature/auth-backend` | 后端权限与数据库 |
| `feature/testing-devops` | 测试、DevOps |
| `assistant-api-integration` | 智能助手 API 集成 |
| `feature/bugfix-core-logic` | 核心业务逻辑修复 |
| `feature/infra-improvements` | 基础设施改进 |
| `fix/token-expire-logout` | Token 过期自动登出 |
| `health-check-test` | 健康检查测试 |

## 开发流程

### 提交前运行测试

```bash
cd backend
python -m unittest discover -s . -p "test_*.py" -v
```

确保所有 29 个测试通过后再创建 PR。

```
1. git checkout feature/xxx                 # 切到自己的分支
2. git pull origin main                      # 拉取最新 main
3. # 编写代码...
4. git add <具体文件>                         # 暂存变更
5. git commit -m "feat: 简短描述"             # 原子提交
6. git push origin feature/xxx               # 推送分支
7. 在 GitHub 上创建 Pull Request → main      # 创建 PR
8. 等待至少一位其他成员 Review                # 代码审查
9. Review 通过后 Merge PR                    # 合并到 main
```

## Commit Message 规范

使用 Conventional Commits 格式：

```
<type>(<scope>): <description>
```

type 类型：
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `test`: 测试用例
- `refactor`: 重构
- `ci`: CI/CD 配置

示例：
```
feat(reservation): add seat conflict detection
fix(checkin): validate room daily code correctly
docs(api): update reservation endpoint spec
test(backend): add reservation overlap test
```

## PR 规范

### PR 标题格式

```
<type>(<scope>): 简短描述
```

### PR 内容模板

```markdown
## 变更说明
- 具体改了什么

### 对应的用户故事
- US-X.X ...

### 检查清单
- [ ] 代码已本地测试通过
- [ ] 不影响已有功能
- [ ] 已更新相关文档
```

### Review 规则

1. 每个 PR 至少需要 **1 位其他成员** Review 通过才能合并
2. Review 重点：
   - 代码逻辑是否正确
   - 是否符合项目架构
   - 是否有明显的 bug 或安全问题
3. Review 意见需具体，不要只写 "LGTM"
4. 如有问题，提出修改建议，作者修改后再次 Review

## 分支同步

每次开始新工作前，先同步 main 的最新代码：

```bash
git checkout feature/xxx
git merge main    # 或 git rebase main
# 解决冲突（如有）
git push origin feature/xxx
```

## 禁止事项

- **禁止** 直接向 `main` 分支 push
- **禁止** 使用 `git push --force`
- **禁止** 在 PR 未 Review 通过时自行 Merge
- **禁止** 提交数据库文件 (`*.db`)、配置文件 (`config.json`)、缓存文件 (`__pycache__/`)
