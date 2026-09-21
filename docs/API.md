# HTTP API

默认服务 `http://127.0.0.1:3210`，仅绑定 loopback。写请求使用 JSON。同源保护检查 Host 和 Origin；无开放 CORS。错误格式 `{ "error": "原因" }`，无效输入返回 400，不存在记录返回 404，外域访问返回 403。

## 状态与技能

| Method | Path                       | 用途                                                              |
| ------ | -------------------------- | ----------------------------------------------------------------- |
| GET    | `/api/health`              | 服务健康状态                                                      |
| GET    | `/api/state`               | 技能、最近 60 条日常执行、最近示范/评测、偏好及统计               |
| GET    | `/api/skills/:id`          | 当前技能                                                          |
| GET    | `/api/skills/:id/versions` | 不可变历史版本                                                    |
| POST   | `/api/skills/:id/restore`  | `{ "version": 1 }`，恢复工作流为新版本                            |
| POST   | `/api/retrieve`            | `{ "task": "帮我生成 Notion 周报" }`，返回 candidates 和 decision |

Skill 和执行记录完整结构定义于 `shared/types.ts`。UI 中可以导出完整 JSON。

## 教学

`POST /api/demonstrations`

```json
{
  "name": "项目周报",
  "task": "生成 Notion 项目周报",
  "app": "notion",
  "mode": "lab"
}
```

应用为 `github | jira | notion | custom`。`mode: "browser"` 时必须提供 `startUrl`，且来源必须已配置；会打开独立的 headed 浏览器。`custom` 仅用于真实浏览器。

- `POST /api/demonstrations/:id/actions`：本地练习事件入口。接收 `kind/target/value/checked/url/timestamp`；只接受当前练习路径与来源。真实浏览器事件仅经 Playwright binding 进入。
- `POST /api/demonstrations/:id/finish`：`{ "postcondition": "Report published successfully" }`；提取并持久化 Skill。真实浏览器录制还会先检查该文本是否已经出现。
- `POST /api/demonstrations/:id/cancel`：停止录制，关闭所持有的独立窗口。

原始事件最大 5000，字段值最长 20000 字符，JSON 请求上限 1MB。教学会忽略密码和识别出的敏感字段，但其他示范字段会存储为参数默认值。

## 执行

`POST /api/runs` 返回 202 及排队记录：

```json
{
  "task": "生成本周周报",
  "skillId": "example-notion",
  "parameters": {
    "report_title": "第 38 周进展",
    "report_content": "本周完成语义技能学习。"
  },
  "variant": "renamed",
  "repairEnabled": true,
  "approved": true
}
```

`variant` 为 `original | renamed | layout | ambiguous`，仅本地练习支持非 original。真实来源执行必须有 `approved: true`。省略的参数使用 Skill 默认值；必填参数为空时拒绝启动。一次只执行一个任务，队列最多接受 20 个等待/运行任务。

- `GET /api/runs/:id`：轮询状态及每步轨迹。
- `GET /api/runs/:id/screenshot`：结束截图，仅对已存在且有截图的记录开放。
- `POST /api/runs/:id/cancel`：取消队列任务或关闭当前任务上下文。

状态为 `queued → running → succeeded | failed | cancelled`。`verified` 独立记录是否通过完成条件。修复尝试数可能大于 0 但 verified 为 false，此时 Skill 不会更新。`reused` 在任务开始时记录该技能是否有以前的执行。

## 评测

- `POST /api/evaluations`：启动一轮固定 24 次浏览器执行；已有运行中的评测时拒绝重复启动。
- `GET /api/evaluations/:id`：状态、逐条件结果、两个运行 ID 和最终指标。

评测轨迹仍可通过 `/api/runs/:id` 打开，但不出现在日常执行列表，也不改变用户偏好。

## 本地页面

`GET /lab/github`、`/lab/jira`、`/lab/notion`。

`?variant=renamed` 等参数施加受控扰动；`?record=<demo-id>` 启用本地 iframe 的事件通知，父页面再通过同源 API 保存。

本服务是单用户本地应用，没有多租户认证，不应直接暴露到公网。需要远程部署时，应增加账号认证、请求身份、会话隔离、限流及部署层授权。
