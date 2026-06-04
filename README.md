<p align="center">
  <img src="https://img.shields.io/badge/version-3.0.0-blue?style=flat-square" alt="version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="python" />
  <img src="https://img.shields.io/badge/react-18-61dafb?style=flat-square&logo=react&logoColor=white" alt="react" />
  <img src="https://img.shields.io/badge/fastapi-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="fastapi" />
  <img src="https://img.shields.io/badge/deploy-Render-46e3b7?style=flat-square&logo=render&logoColor=white" alt="render" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="license" />
</p>

<h1 align="center">Rule Harness &mdash; 法律规则梳理平台</h1>

<p align="center">
  <strong>上传法律文件 &rarr; 智能分类归档 &rarr; 自动抽取规则 &rarr; 一键生成可部署的 AI Skill</strong>
</p>

<p align="center">
  从混合法律文档中提取结构化审查规则，并打包为可直接加载的法务 AI 平台 Skill。<br/>
  <a href="https://rules.448898.xyz"><strong>在线体验</strong></a> &nbsp;|&nbsp; Render 免费实例首次访问可能需等待几十秒唤醒
</p>

---

## 核心能力

| 模块 | 功能 | 状态 |
|------|------|------|
| **规则抽取引擎** | 五条并行管道，从合同/法规/裁判文书中抽取结构化规则 | v2.0 稳定 |
| **文件智能归档** | 上传文件自动识别类型，整理到结构化目录 | v3.0 新增 |
| **Skill 生成器** | 将抽取的规则组装为完整的法务 AI Skill ZIP 包 | v3.0 新增 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │
│  │  任务工作台   │  │  文件归档     │  │  审查结果     │  │  设置   │ │
│  │ WorkbenchView│  │ ArchiveView  │  │ ResultsView  │  │Settings │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────────┘ │
│         │                 │                 │                       │
│         ▼                 ▼                 ▼                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    api.ts (Unified API Layer)               │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ HTTP / SSE
┌─────────────────────────────▼───────────────────────────────────────┐
│                      Backend (FastAPI + Python)                     │
│                                                                     │
│  ┌──────────────────────┐  ┌──────────────────────┐                 │
│  │   archive_routes.py  │  │   batch_routes.py    │                 │
│  │  POST /archive/*     │  │  POST /batches       │                 │
│  └──────────┬───────────┘  │  POST /generate-skill│                 │
│             │              └──────────┬───────────┘                 │
│             ▼                         ▼                             │
│  ┌──────────────────┐   ┌──────────────────────────────────────┐   │
│  │  archive_engine   │   │          orchestrator.py             │   │
│  │  ┌──────────────┐ │   │  parse → pipelines → dedupe →       │   │
│  │  │doc_profile.py│ │   │  confidence → merge → export        │   │
│  │  └──────────────┘ │   └──────────────────┬──────────────────┘   │
│  │  ┌──────────────┐ │                      │                      │
│  │  │  LLM 增强    │ │                      ▼                      │
│  │  └──────────────┘ │   ┌──────────────────────────────────────┐  │
│  └──────────────────┘   │         skill_builder.py              │  │
│                          │  rules → 6维度分组 → 场景拆分 →      │  │
│                          │  模板填充 → CSV导出 → ZIP打包        │  │
│                          └──────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  llm.py  │  storage.py (SQLite)  │  parsers.py  │  state.py │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三大功能模块

### 1. 规则抽取引擎

从法律文件中自动提取结构化审查规则，核心流程：

```
上传文件 → 解析(DOCX/PDF/XLSX/TXT) → 五管道并行抽取 → 去重 → 置信度评分 → 合并入库 → 多格式导出
```

**五条抽取管道**

| 管道 | 标识 | 用途 |
|------|------|------|
| 正文抽取 | P1 | 从合同/法规正文中逐段提取规则 |
| 批注抽取 | P2 | 从 Word 文档批注中提取审查意见 |
| 修订对比 | P3 | 从修订标记中推断规则变更 |
| 谈判红线 | P4 | 从红线清单中提取不可逾越的底线（三阶降级梯） |
| 案例反推 | P5 | 从裁判文书中反推事前审查规则 |

**质量保障体系**

- **五级来源优先级**：法规 > 公司红线 > 内部制度 > 标准条款库 > 历史合同
- **五重门置信度评分**：自评分 + 一致性采样 + 结构校验 + 冲突检测 + 数值忠实度
- **语态校验**：检测软语态原文被错误写成强义务的情况
- **占位规则分流**：自动识别并分离含 `【】`、`XX天` 等模式的模糊规则

**导出格式**

| 文件 | 内容 |
|------|------|
| `main.csv` | 实质规则（七字段） |
| `metadata.csv` | 完整元数据（30+ 字段） |
| `negotiation.csv` | 谈判阶梯规则 |
| `placeholders.csv` | 占位/模糊规则 |
| `discarded.csv` | 忠实度不达标的弃用规则 |
| `out_of_scope.csv` | 超出当前模板范围的规则 |
| `conflict_report.html` | 冲突分析报告 |
| `summary.html` | 批次摘要 |

---

### 2. 文件智能归档 <sub>v3.0</sub>

上传混合法律文件，自动识别文档类型并整理到结构化目录。

```
拖拽上传 → 规则匹配分类 → (可选)LLM 二次分类 → 预览 & 手动调整 → 确认归档
```

**分类体系**

```
archived/
├── 法律法规/
│   ├── 国家法律/            # 民法典、公司法等
│   ├── 司法解释/            # 最高院司法解释
│   ├── 部门规章/            # 证监会、财政部规章
│   ├── 地方文件/            # 地方红头文件
│   └── 司法问答/            # 答记者问、审判实务问答
├── 合同文本/
│   ├── 模板/               # 合同范本、示范文本
│   ├── 历史合同/            # 已签署合同
│   └── 股权转让/            # 股权转让专项
├── 裁判文书与案例/
│   ├── 案例/               # 判例、裁判文书
│   └── 司法指引/            # 裁判指引、审判实务
├── 内部制度/
│   ├── 公司红线/            # 底线清单、谈判底线
│   ├── 管理制度/            # 内控、操作规程
│   ├── 标准条款/            # 审查手册、规则库
│   └── 业务规范/            # 业务操作规范
├── 已有规则/
│   ├── 规则库/              # 已有 CSV 规则表
│   └── 审查清单/            # 审查要点清单
└── 行业资料/
    └── 特殊资料/
```

**双层分类机制**

- **第一层 — 规则匹配**（零 API 调用）：基于文件名关键词 + 正文特征词 + 文档结构的评分分类
- **第二层 — LLM 增强**（可选）：对置信度低于 50% 的文件调用 LLM 做二次分类

每次归档自动生成 `_归档清单.json` 元数据索引，记录每个文件的分类依据和置信度。

---

### 3. Skill 生成器 <sub>v3.0</sub>

将已抽取的规则打包为符合**法务 AI 平台规范**的完整 Skill 目录（纯 Markdown + CSV），可直接下载 ZIP 并部署到 Claude 等 AI 平台。

```
选择批次规则 → 配置领域名称/主体立场 → 六维度分组 → 按立场拆分 → 模板填充 → ZIP 下载
```

**生成的 Skill 目录结构**

```
<领域>审查与起草/
├── SKILL.md                                # 主入口（frontmatter + 场景调用说明）
├── references/
│   ├── 通用要点与纪律.md                     # 六维度兜底自检
│   ├── 任务路由（审查与起草识别）.md          # 审查/起草判定 + 场景路由
│   ├── 审查规则-<立场A>立场.md               # 按立场拆分的审查规则
│   ├── 审查规则-<立场B>立场.md
│   ├── 起草要点与范例.md                     # 起草必备要素 + 条款五层结构
│   ├── 术语表.md                            # 领域专有术语
│   └── 规则登记表（CSV字段）.md              # 规则单一事实源（七字段）
└── 导出/
    └── rules.csv                           # 法天使平台导入物（UTF-8 BOM）
```

**六维度规则分组**

| 维度 | 前缀 | 覆盖范围 |
|------|------|----------|
| 主体资格 | SU | 签约资质、经营范围、授权 |
| 付款条件 | PA | 付款节点、币种、发票、逾期利息 |
| 违约责任 | BR | 违约金上限、解除条件、赔偿 |
| 知识产权 | IP | 权属归属、许可范围、侵权担保 |
| 保密条款 | CF | 保密范围、期限、违约后果 |
| 争议解决 | DR | 管辖/仲裁、适用法律、送达 |

---

## 快速开始

### 方式一：在线体验

直接访问 **[rules.448898.xyz](https://rules.448898.xyz)**，无需安装。

> Render 免费实例空闲后会休眠，首次打开可能需等待几十秒唤醒。

### 方式二：本地运行

```bash
# 克隆
git clone https://github.com/SenryLee/rule-harness.git
cd rule-harness

# 后端
pip install -e ".[dev]"

# 前端
cd frontend && npm install && cd ..

# 启动（后端 :8765 + 前端 :5199）
python -m backend.app
```

首次运行自动生成 `data/config.yaml`，编辑其中的 API Key 即可。

### 方式三：Docker

```bash
docker build -t rule-harness .
docker run -p 8765:8765 -e PORT=8765 rule-harness
```

### 方式四：Render 一键部署

项目已包含 `render.yaml`，fork 后在 Render Dashboard 选择 Blueprint 即可。

---

## 模型配置

在「系统设置 → 模型配置」中选择 LLM 提供方，支持：

| 提供方 | Provider 值 | 备注 |
|--------|-------------|------|
| DeepSeek | `deepseek` | 默认推荐，性价比高 |
| 通义千问 (DashScope) | `openai` | 兼容 OpenAI 接口 |
| 小米 MiMo | `mimo` | 自动关闭 thinking，稳定返回 JSON |
| OpenAI | `openai` | GPT-4o 等 |

---

## 技术栈

| 层 | 技术 |
|----|------|
| **前端** | React 18 + TypeScript + Vite 5 + Tailwind CSS 3 |
| **后端** | FastAPI + Uvicorn + asyncio |
| **文件解析** | python-docx / PyMuPDF / pdfplumber / openpyxl / lxml |
| **LLM 集成** | aiohttp（主/备双路由，自动限速，指数退避重试） |
| **数据存储** | SQLite（规则库）+ 文件系统（导出/归档） |
| **部署** | Docker 多阶段构建 / Render |

---

## 项目结构

```
.
├── backend/
│   ├── app.py                    # FastAPI 入口，路由注册，静态文件挂载
│   ├── orchestrator.py           # 批次编排器：解析 → 管道 → 去重 → 导出
│   ├── archive_engine.py         # 文件归档引擎：分类 + LLM增强 + 目录生成
│   ├── skill_builder.py          # Skill 组装器：规则 → 六维度 → 场景拆分 → ZIP
│   ├── llm.py                    # LLM 路由器（主/备切换，速率控制，指数退避）
│   ├── parsers.py                # 文件解析器（DOCX / PDF / XLSX / TXT）
│   ├── document_profile.py       # 文档画像（规则式文档类型分类）
│   ├── preview.py                # 上传预分类（来源 + 合同类型 + 立场）
│   ├── dedupe.py                 # 五级来源优先级去重
│   ├── confidence.py             # 五重门置信度评分
│   ├── fidelity.py               # 数值忠实度校验门
│   ├── voice_check.py            # 软硬语态检测
│   ├── placeholder_detector.py   # 占位规则识别
│   ├── merger.py                 # 规则合并决策（new / update / skip / conflict）
│   ├── exporter.py               # 多格式导出（CSV / HTML / Markdown）
│   ├── storage.py                # SQLite 持久层
│   ├── state.py                  # 进程内批次状态
│   ├── config.py                 # 配置加载与序列化
│   ├── pipelines/
│   │   ├── p1_body.py            # P1 正文抽取管道
│   │   ├── p2_comment.py         # P2 批注抽取管道
│   │   ├── p3_revision.py        # P3 修订对比管道
│   │   ├── p4_redline.py         # P4 红线抽取管道
│   │   ├── p5_case.py            # P5 案例反推管道
│   │   └── direct_passthrough.py # Excel 清单直通转换
│   └── routes/
│       ├── archive_routes.py     # 归档 API（classify / confirm / browse）
│       ├── batch_routes.py       # 批次 + Skill 生成 API
│       ├── config_routes.py      # 配置 API
│       └── rule_routes.py        # 规则库 API
├── frontend/src/
│   ├── App.tsx                   # 应用外壳 + 视图路由
│   ├── api.ts                    # 统一 API 层（规则 + 归档 + Skill）
│   ├── context/AppContext.tsx    # 全局状态管理
│   └── components/
│       ├── WorkbenchView.tsx     # 任务工作台（上传 + 预分类 + 启动）
│       ├── ArchiveView.tsx       # 文件归档（拖拽 → 分类 → 目录树）
│       ├── ResultsView.tsx       # 审查结果 + Skill 生成面板
│       ├── SettingsView.tsx      # 系统设置
│       ├── TaskPanel.tsx         # 侧边栏导航 + 历史任务列表
│       ├── PipelineProgress.tsx  # 五管道实时进度可视化
│       └── Ui.tsx                # 图标 + 基础组件库
├── profiles/                     # 行业预设配置（金融 / 医药 / IT 等）
├── samples/                      # 测试样本文件
├── Dockerfile                    # 多阶段构建（Node → Python）
├── render.yaml                   # Render 部署配置
├── config.default.yaml           # 默认配置模板
└── pyproject.toml                # Python 项目元数据
```

---

## API 概览

### 规则抽取

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/batches` | 创建批次，上传文件并启动抽取 |
| `GET` | `/api/batches/{id}/progress/stream` | SSE 实时进度推送 |
| `GET` | `/api/batches/{id}/rules` | 获取规则列表（分页 / 过滤） |
| `GET` | `/api/batches/{id}/exports/main-csv` | 下载主 CSV |
| `POST` | `/api/batches/{id}/apply` | 合并规则到主库 |

### 文件归档

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/archive/classify` | 上传文件，返回分类预览 |
| `PUT` | `/api/archive/classify/{session}` | 手动调整分类结果 |
| `POST` | `/api/archive/confirm/{session}` | 确认归档，执行文件整理 |
| `GET` | `/api/archive/categories` | 获取完整分类体系 |

### Skill 生成

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/batches/{id}/generate-skill` | 从批次规则生成 Skill |
| `GET` | `/api/batches/{id}/exports/skill-zip` | 下载 Skill ZIP 包 |

---

## 行业预设

通过配置面板选择行业，自动调整词表、关注要点和优先级权重：

建工总包 · 建工勘察设计 · 房地产 · 金融 · 医药 · IT · 制造 · 能源电力 · 汽车 · 通用商事

---

## 版本历史

| 版本 | 主要变更 |
|------|----------|
| **v3.0.0** | 新增文件智能归档（规则匹配 + LLM 增强）、Skill ZIP 生成器（六维度 + 场景拆分） |
| **v2.0.0** | 路由重构、批次 UI 改版、文档画像、任务模式（全量/模板/策略） |
| **v1.1** | 忠实度门、语态校验、占位规则分流、范围匹配 |
| **v1.0** | 五管道抽取、去重、置信度评分、合并入库、多格式导出 |

---

## License

MIT
