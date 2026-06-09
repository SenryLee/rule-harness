# 规则梳理工具接入 Dify —— 可行性 / 实施 / 效果保障方案

> 结论先行：**能做，但不要把"上传文件"做成 workflow 里的自定义工具。** 自定义工具最适合那几个"纯 GET / 传字符串"的读接口；上传文件这一步要用 HTTP 请求节点（或干脆让文件走 Dify 自己的上传），整条链路必须按"上传→拿 batch_id→轮询→取结果 JSON"的异步模式编排。你现有的 `backend/routes/dify_routes.py` 已经把异步骨架搭对了，主要补三件事：状态持久化、鉴权、大文件兜底。

---

## 1. 能不能做？（可行性）

**能。** 但有两个 Dify 的硬约束决定了"怎么接"，绕不开：

### 约束 A：Workflow 里的自定义工具无法稳定绑定"文件类型变量"
- Dify 自定义工具（OpenAPI 导入）从 0.12/0.13 起支持 `multipart/form-data` 文件参数（schema 写 `type: string, format: binary`，PR #10796）。
- 但有长期未解的已知问题：**在 workflow 中，自定义工具的文件参数只接受 String，无法把 `sys.files` / 文件变量绑进去**（issues #9605 / #11644 / #21235）。也就是说：把"上传文件"做成自定义工具、在工作流里喂文件——不可靠。
- 它在 Agent / 直接调用、带文件上传的 chatflow 里能用，但在 workflow 节点里绑定文件变量会踩坑。

→ **取舍**：文件上传这一步改用 **HTTP 请求节点**（body 选 Binary，引用上一节点的文件变量），它对 `sys.files` 的支持比自定义工具好。读接口（状态、结果 JSON）继续用自定义工具——它们是纯 GET、只传字符串，完全没问题（就是你截图里"国家标准查询"那种形态）。

### 约束 B：工具 / HTTP 节点调用大约 1 分钟超时
- workflow 里的工具调用 / HTTP 节点超过约 60s 会超时报错（issues #4545 / #5982，云网关层 Cloudflare 也会切）。
- 你的抽取是 LLM 密集型、耗时以分钟计。**所以"上传并同步等结果"在 Dify 里物理上做不到。**

→ **取舍**：必须异步。上传接口立即返回 `batch_id`，再用轮询节点查状态，完成后再取 JSON。**这正是 `dify_routes.py` 已经实现的模式**，方向完全正确。

### 一句话可行性判断
| 步骤 | 用什么接 | 可行性 |
|------|----------|--------|
| 上传文件触发抽取 | HTTP 请求节点（Binary body 引用 `sys.files`） | ✅ 可行（注意大文件，见 §3） |
| 轮询批次状态 | 自定义工具（GET，传 `batch_id` 字符串） | ✅ 完全可行 |
| 取规则结果 JSON | 自定义工具（GET，传 `batch_id` 字符串） | ✅ 完全可行 |
| "上传文件"做成自定义工具 | ❌ 不推荐 | workflow 无法稳定绑文件变量 |
| 上传后同步等抽取结果 | ❌ 做不到 | 60s 超时 |

---

## 2. 怎么做？（实施方案）

### 2.1 后端接口（基本已就绪，需小改）
你已经有：
- `POST /api/dify/upload` —— multipart 收文件，建批次，后台跑抽取，立即返回 `{batch_id, status, total_files}`
- `GET /api/dify/batches/{batch_id}/status` —— 返回 `status / total_rules / summary`
- `GET /api/dify/batches/{batch_id}/rules.json` —— 运行中返回 409，完成后返回规则 JSON

需要补的（详见 §3 风险）：
1. **状态持久化**：`state.batches` / `state.batch_rules` 现在是纯内存字典（`state.py` 已注明仅进程内有效）。Render 免费实例会休眠、重启、甚至多 worker，轮询可能打到没有该 batch 的进程 → 404。**必须把批次生命周期落到 SQLite（`storage.py` 已有持久层，扩一张 `dify_batches` 表即可）。**
2. **鉴权**：截图里"鉴权方法=请求头"。给 `/api/dify/*` 加一个 API Key 头校验（如 `Authorization: Bearer <key>` 或自定义 `X-API-Key`），与 Dify 自定义工具的"请求头鉴权"对齐。
3. **部署单 worker 或共享状态**：若用 gunicorn 多 worker，内存态必失效——落库后此问题自然消除。

### 2.2 Dify 侧编排（workflow）
推荐节点链路：

```
开始(File 输入)
  └─ HTTP请求节点①  POST {base}/api/dify/upload   (Binary body 引用 sys.files) → 得到 batch_id
       └─ 迭代/循环节点  ──► HTTP请求 或 自定义工具② GET .../status
            │                          ├─ status == "success"/"partial" → 跳出
            │                          └─ 否则 等待(若干秒) 再次轮询（设最大次数兜底）
            └─ 自定义工具③ GET .../rules.json  → 解析规则
                 └─ LLM/代码节点  做后续处理 / 回显
```

- **轮询**：用 Loop / Iteration 节点 + 条件分支判断 `status`，加 `wait` 节点拉开间隔（如每 5–10s），并设最大轮询次数（如 60 次 ≈ 10 分钟）防死循环。
- **base URL**：你的后端线上地址是 `https://rules.448898.xyz`（README），OpenAPI schema 的 `servers` 填这个。

### 2.3 自定义工具的 OpenAPI Schema（状态 + 结果，直接可导入）
这两个是"安全"的读接口，按下面 schema 在 Dify"创建自定义工具→从 URL/粘贴导入"即可（与"国家标准查询"同款形态）：

```yaml
openapi: 3.0.1
info:
  title: 规则梳理 Harness - Dify 读接口
  version: 1.0.0
servers:
  - url: https://rules.448898.xyz
paths:
  /api/dify/batches/{batch_id}/status:
    get:
      operationId: getBatchStatus
      summary: 查询批次抽取状态
      description: 轮询批次状态，status 为 success/partial 时表示完成。
      parameters:
        - name: batch_id
          in: path
          required: true
          schema: { type: string }
          description: 上传接口返回的批次 ID
      responses:
        "200":
          description: OK
  /api/dify/batches/{batch_id}/rules.json:
    get:
      operationId: getBatchRules
      summary: 获取批次规则结果(JSON)
      description: 抽取完成后获取规则数组；运行中返回 409。
      parameters:
        - name: batch_id
          in: path
          required: true
          schema: { type: string }
      responses:
        "200":
          description: OK
```

> 鉴权：在工具的"鉴权方法→请求头"里配置与后端约定的 Header（如 `X-API-Key`）。

### 2.4 上传步骤（HTTP 请求节点，不是自定义工具）
- Method `POST`，URL `https://rules.448898.xyz/api/dify/upload`
- Body 类型选 **form-data / Binary**，把 `files` 字段绑到 `sys.files`（或开始节点的 File List 变量）
- **不要手动设 `Content-Type: multipart/form-data`**（手填会缺 boundary 导致解析失败，#20322）——让客户端自动加
- 其余字段（`source_tag` / `priority` / `contract_types`）作为普通表单字段
- 从响应体取 `{{①.body.batch_id}}` 传给后续轮询节点

---

## 3. 效果是否有保障？（风险与缓解）

| # | 风险 | 触发条件 | 影响 | 缓解 |
|---|------|----------|------|------|
| R1 | **批次状态丢失** | 内存态 + 实例休眠/重启/多 worker | 轮询 404，整条流失败 | **落库 SQLite**（最高优先级）；部署单 worker 过渡 |
| R2 | 大文件上传失败 | HTTP 节点 form-data 上传 ≳2MB（#11425/#20322） | 上传报错 | 限制单文件大小；或先传 Dify `/v1/files/upload` 拿 ID 再以 JSON 传；或后端支持分片/URL 拉取 |
| R3 | 工具调用 60s 超时 | 误把"等结果"做成同步 | 报 timed out | 严格走异步轮询（上传只回 batch_id，已实现） |
| R4 | 文件变量绑不进自定义工具 | 把上传做成 workflow 自定义工具 | 文件传不过去 | 上传用 HTTP 节点（§2.4） |
| R5 | Render 冷启动 | 免费实例休眠后首次访问 | 首调延迟几十秒 | 第一个轮询自然唤醒；或加保活/升级实例；轮询超时上调 |
| R6 | 轮询死循环 | status 永不变 success | 卡住/超额 | 循环设最大次数 + 处理 `partial`/`failed` 分支 |
| R7 | 无鉴权被滥用 | `/api/dify/*` 公网裸奔 | 资源/费用风险 | 加 API Key 头校验（§2.1） |
| R8 | 抽取质量波动 | LLM 非确定性、长文档 | 规则数量/质量不稳 | 非 Dify 层问题；靠现有置信度/忠实度门 + 结果可在 Dify 内复核 |

**保障结论**：在**完成 R1（状态落库）+ R4（上传走 HTTP 节点）+ R3（坚持异步）** 三项后，链路是可靠的；R2/R5/R7 是工程化收尾项。**当前最大的单点隐患是 R1——内存态在生产/休眠环境下几乎一定会出问题，必须先解决。**

---

## 4. 建议的落地顺序
1. 后端：批次生命周期落 SQLite（R1）→ 加 API Key 头校验（R7）→ 大文件大小限制与报错信息（R2）。
2. 用 curl / Postman 跑通 `upload → status → rules.json` 三步（脱离 Dify 先验证后端）。
3. Dify：导入 §2.3 两个自定义工具；搭 §2.2 workflow（HTTP 上传 + 循环轮询 + 取结果）。
4. 端到端：传一份真实样本，验证 batch_id 贯通、轮询正确跳出、规则 JSON 可解析。
5. 调优：轮询间隔/上限、超时、冷启动等待。

> 需要的话，我可以接着：①写状态落库 + 鉴权的后端改动；②生成可直接导入的完整 OpenAPI 文件；③出一份可直接套用的 Dify workflow 节点配置清单。

---

*依据：Dify 官方 HTTP Request 文档，及 GitHub issues #9605 / #11644 / #21235 / #10796（自定义工具文件参数）、#4545 / #5982（工具超时）、#11425 / #20322（HTTP 节点文件上传）。*
