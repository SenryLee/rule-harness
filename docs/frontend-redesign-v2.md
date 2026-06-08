# 规则梳理平台 — 前端重新设计方案 v2

## 一、设计目标

从"单次任务工具"升级为"规则管理平台"：
- 用户不再只是"上传 → 等结果 → 导出"的线性流程
- 规则库成为核心资产，可长期积累、检索、管理
- Dify 集成有独立管理面板
- 每个页面职责单一、认知负担低

---

## 二、信息架构

### 一级导航（左侧边栏，始终可见）

| 图标 | 名称 | 路由 | 职责 |
|------|------|------|------|
| 📊 | Dashboard | `/` | 首页概览，核心指标 + 快捷入口 |
| 📋 | 规则库 | `/rules` | 跨批次全量规则浏览、搜索、管理 |
| ⚡ | 任务中心 | `/tasks` | 上传 → 抽取 → 结果的完整流程 |
| 🔗 | Dify 集成 | `/integrations` | API 配置、Dify 批次管理、JSON 下载 |
| ⚙️ | 系统设置 | `/settings` | 模型、参数、优先级、置信度 |

### 二级路由

```
/                          → Dashboard
/rules                     → 规则库列表
/rules/:ruleId             → 规则详情（可选，或用侧抽屉）
/tasks                     → 任务列表（历史批次）
/tasks/new                 → 新建任务（Stepper 流程）
/tasks/:batchId            → 单批次详情/结果
/integrations              → Dify 集成面板
/settings                  → 系统设置（子 Tab 保持现有）
```

---

## 三、各页面设计

### 1. Dashboard（新增）

**布局：** 上方指标卡片行 + 下方两栏

**指标卡片（一行 4 个）：**
- 规则总量（累计入库数）
- 高风险规则数
- 本周新增规则
- Dify 接入状态（在线/离线）

**左栏（60%）：最近任务**
- 最近 5 个批次的状态卡片（状态、文件数、规则数、时间）
- 点击跳转 `/tasks/:batchId`

**右栏（40%）：快捷操作 + 待处理**
- "新建任务"按钮
- 待处理冲突数量（可点击跳转规则库筛选冲突）
- 需复核规则数（置信度 < 0.7）

### 2. 规则库（核心升级）

**现状问题：** 规则只能在单个批次内查看，无法跨批次管理。

**新设计：**
- 顶部：搜索栏 + 筛选器（风险等级、领域、主题、来源批次、启用状态）
- 视图切换：表格视图 / 卡片视图
- 表格列：规则ID、风险、检查项、审查要求、主题、来源、置信度、状态
- 点击行 → 右侧滑出详情抽屉（复用现有 DetailDrawer）
- 批量操作：选中 → 导出选中（JSON/CSV）、批量启用/停用
- 分页 + 总数显示

**数据来源：** 调用 `/api/rules` 接口（已有）

### 3. 任务中心（Stepper 改造）

**3.1 任务列表页 `/tasks`**
- 历史批次表格（从现有 TaskPanel 侧边栏提取为独立页面）
- 筛选：状态、时间范围、来源（手动/Dify）
- 右上角"新建任务"按钮 → 跳转 `/tasks/new`

**3.2 新建任务 `/tasks/new`（四步 Stepper）**

**Step 1 — 上传文件**
- 大面积拖拽区（居中，视觉焦点）
- 已添加文件列表（名称 + 大小 + 移除）
- 扫描件标记
- 底部：「下一步」按钮

**Step 2 — 确认分类 & 配置**
- 每个文件的 AI 预分类结果（类型标签、置信度）
- 领域选择网格（覆盖 AI 判断）
- 任务模式选择
- 折叠区：高级配置（颗粒度、法规深度、我方立场、范围说明）
- Token 预算提示
- 底部：「上一步」「开始抽取」

**Step 3 — 执行进度**
- 步骤条显示当前在 Step 3
- 管道级进度（保持现有 PipelineProgress 组件）
- 实时规则产出计数
- 错误/警告展示
- 完成后自动进入 Step 4

**Step 4 — 结果审阅**
- 统计摘要卡片
- Tab 分桶（实质/占位/弃用/谈判/范围外）
- 规则表格 + 详情抽屉
- 导出：下拉菜单式（不再是一排按钮）
  - 分组：主要输出 / 审计文件 / 分桶导出 / 高级
- 操作按钮：「应用入库」「生成 Skill」

### 4. Dify 集成页（新增）

**上半部分：接入配置**
- Endpoint 地址展示（自动检测当前域名 + 端口）
- Dify HTTP 节点配置代码示例（可复制）
- 接入状态指示灯

**下半部分：Dify 批次管理**
- 表格：batch_id、状态、文件数、规则数、时间
- 筛选 `source === "dify"` 的批次
- 每行操作：查看结果、下载 JSON、删除
- 一键下载 JSON 按钮

### 5. 系统设置（保持，微调）

- 保持现有 Tab 结构（模型/抽取/优先级/置信度/高级）
- 无大改动，仅样式统一

---

## 四、组件设计要点

### 导出菜单组件（替代底部按钮行）
```
┌─────────────────┐
│ 📥 导出         ▾│
├─────────────────┤
│ 主要输出         │
│   主 CSV         │
│   规则 JSON      │  ← 新增
│ ─────────────── │
│ 审计文件         │
│   元数据 CSV     │
│   冲突报告 HTML  │
│   变更集 CSV     │
│ ─────────────── │
│ 分桶导出         │
│   占位 CSV       │
│   弃用 CSV       │
│   谈判阶梯 CSV   │
│   范围外 CSV     │
│ ─────────────── │
│ 高级             │
│   模板骨架 MD    │
│   Skill ZIP      │
└─────────────────┘
```

### 全局搜索（⌘K 升级）
- 搜索规则内容（check_item、requirement）
- 搜索批次 ID
- 快捷动作（新建任务、打开设置）
- 结果列表可直接跳转

### 侧边栏改造
- 移除历史任务列表（改为任务中心独立页面）
- 只保留导航项 + Logo + 版本号
- 折叠/展开支持（响应式）

---

## 五、技术变更

| 项目 | 现状 | 目标 |
|------|------|------|
| 路由 | 无（state 驱动） | react-router-dom v6（已安装） |
| 数据获取 | useEffect + useState | @tanstack/react-query（缓存、自动刷新） |
| 图标 | 自定义 SVG map | lucide-react（更完整，按需导入） |
| 状态管理 | Context + useState | 保持 Context，路由参数替代部分 state |
| 样式 | Tailwind + CSS vars | 保持，增加 headlessui 用于下拉/对话框 |
| 构建 | Vite 5 | 保持 |

### 新增依赖
```json
{
  "@tanstack/react-query": "^5.x",
  "lucide-react": "^0.400+",
  "@headlessui/react": "^2.x"
}
```

---

## 六、实施阶段

### Phase 1 — 骨架 & 路由（基础设施）
- 启用 react-router，配置路由表
- 重写侧边栏为纯导航
- 各页面先用空壳占位
- 引入 tanstack-query + lucide-react

### Phase 2 — 核心页面迁移
- Dashboard：新建
- 规则库：基于现有 RulesView 扩展
- 任务中心列表：从 TaskPanel 提取
- 系统设置：直接迁移

### Phase 3 — 任务 Stepper 改造
- 拆分 WorkbenchView 为 4 步
- 迁移 ResultsView 为 Step 4
- 保持 PipelineProgress 组件

### Phase 4 — Dify 集成 & 精细化
- Dify 集成页面
- 导出下拉菜单组件
- 全局搜索升级
- 响应式适配

---

## 七、视觉设计规范（Apple 官网风格）

### 配色方案 — 近乎单色 + 一个强调色

| 用途 | 色值 | 说明 |
|------|------|------|
| 正文黑 | `#1d1d1f` | 标题、正文 |
| 次级灰 | `#424245` | 副标题、次要文字 |
| 辅助灰 | `#86868b` | 描述文字、placeholder |
| 分割线 | `#d2d2d7` | 边框、分割 |
| 背景灰 | `#f5f5f7` | 页面背景、卡片悬浮底 |
| 纯白底 | `#fbfbfd` | 卡片、内容区 |
| Apple 蓝 | `#0071e3` | 唯一强调色，仅用于主 CTA |
| 蓝 Hover | `#147ce5` | 按钮 hover 态 |
| 风险高 | `#bf4800` | 语义-警告 |
| 风险中 | `#b25000` | 语义-注意 |
| 安全 | `#007a3d` | 语义-成功 |

### 排版

- 页面标题：24px Semibold（-apple-system / SF Pro Display）
- 区块标题：17px Semibold
- 正文：14px Regular，行高 1.6
- 代码/ID：12px SF Mono
- 字间距：正常，不加 letter-spacing

### 间距 & 圆角

- 卡片圆角：12px（不要更大）
- 按钮圆角：8px（实心按钮不用全圆）
- 页面两侧边距：48～64px
- 内容最大宽度：1080px，居中
- 阴影：几乎不用，靠 1px border + 留白分层

### 动效规范

| 场景 | 属性 | 持续时间 | 缓动函数 |
|------|------|----------|----------|
| 页面切换 | opacity + translateY(12→0) | 400ms | cubic-bezier(0.25, 0.1, 0.25, 1) |
| 卡片 Hover | translateY(-2px) | 300ms | ease-out |
| 按钮点击 | scale(0.97→1) | 150ms | ease |
| 列表项入场 | opacity + translateY(8→0) stagger 50ms | 300ms | ease-out |
| 抽屉滑入 | translateX(100%→0) | 350ms | cubic-bezier(0.32, 0.72, 0, 1) |

### 禁止（去 AI 工具化）

- ✕ 蓝紫渐变背景、彩虹色分割线
- ✕ Sparkle/魔法棒图标满天飞
- ✕ 过多 Badge/Tag 堆叠导致信息密度过高
- ✕ 深色侧边栏 + 亮色主区的强对比分裂
- ✕ Ripple 波纹点击效果
- ✕ 过度使用 shadow（尤其 elevation 分层）

### 要

- ✓ 大面积白/浅灰留白，内容有呼吸感
- ✓ 单一强调色（#0071e3），只用在关键 CTA
- ✓ 微妙的 1px 边框分区
- ✓ 表格行间距宽松（py-4），字号不缩到 11px
- ✓ 按钮用 scale 物理位移而非色彩变化表达反馈
- ✓ 空状态用简洁插图 + 一句引导语

---

## 八、Dify 工作流集成架构

本项目已完全支持作为 Dify 工作流节点使用：

```
Dify 工作流:
  ┌─────────────────────────────────────────────────┐
  │  HTTP Request 节点                                │
  │  POST /api/dify/upload                           │
  │  Body: form-data { files, source_tag, priority } │
  │  → 返回 { batch_id }                             │
  └──────────────────────┬──────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────┐
  │  循环/条件节点                                    │
  │  GET /api/dify/batches/{batch_id}/status          │
  │  → 当 status !== "running" 时退出循环             │
  └──────────────────────┬──────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────┐
  │  HTTP Request 节点                                │
  │  GET /api/dify/batches/{batch_id}/rules.json      │
  │  → 结构化 JSON 传入下游节点                        │
  └─────────────────────────────────────────────────┘
```

三个 endpoint 均已在 `backend/routes/dify_routes.py` 中实现。

---

## 九、不动的部分

- **后端 API**：全部保持不变，前端只是换界面
- **CSS 设计语言**：保持现有色彩体系、圆角、间距变量
- **功能逻辑**：所有业务逻辑不变，只是重新组织展示层
- **api.ts**：保持现有 API 调用函数，只新增少量

---

## 十、文件结构预览

```
frontend/src/
├── main.tsx
├── App.tsx                    # 路由配置 + Layout
├── api.ts                     # 保持
├── index.css                  # 保持
├── layouts/
│   └── MainLayout.tsx         # 侧边栏 + 主内容区
├── pages/
│   ├── Dashboard.tsx
│   ├── RuleLibrary.tsx
│   ├── TaskList.tsx
│   ├── TaskNew.tsx            # Stepper 容器
│   ├── TaskDetail.tsx         # 单批次结果
│   ├── Integrations.tsx       # Dify 集成
│   └── Settings.tsx
├── components/
│   ├── Sidebar.tsx            # 纯导航
│   ├── CommandPalette.tsx
│   ├── ExportMenu.tsx         # 下拉导出
│   ├── RuleTable.tsx          # 可复用规则表格
│   ├── RuleDetailDrawer.tsx   # 规则详情抽屉
│   ├── PipelineProgress.tsx   # 保持
│   ├── stepper/
│   │   ├── StepUpload.tsx
│   │   ├── StepClassify.tsx
│   │   ├── StepProgress.tsx
│   │   └── StepResults.tsx
│   └── ui/
│       ├── Icon.tsx           # lucide-react 封装
│       ├── Badge.tsx
│       ├── Card.tsx
│       └── MetricCard.tsx
└── hooks/
    ├── useRules.ts            # tanstack-query
    ├── useBatches.ts
    └── useConfig.ts
```
