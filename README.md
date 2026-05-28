# 规则梳理 Harness

AI 驱动的法律合同/合规文件规则提取工具。从异构法律文档中自动抽取结构化、可执行的审查规则。

**在线体验**：[Render Demo](https://rule-harness-demo.onrender.com)

> Render 免费实例长时间空闲后会休眠，首次打开可能需要等待几十秒唤醒。

## 功能特性

- **5 条并行抽取管线**：正文（P1）、批注（P2）、修订（P3）、谈判红线（P4，三阶降级梯）、判例否定规则（P5）
- **Excel 清单直通**：90% token 节省
- **原子规则分解**：基于命题数 N / 阈值 M / 主体 K / 方向 D 的形式化决策树
- **五重门置信度评分**：自评、一致性采样、结构校验、冲突检测、数值忠实度（v1.1）
- **数值幻觉防护**：规则中每个数字必须有源文本锚点
- **软硬语气检测**：防止 LLM 将"一般 3%"升级为"不得低于 3%"
- **占位符规则隔离**：含 `【】`、`XX天` 等模式的规则自动分离
- **优先级去重**：法规 > 公司红线 > 内部制度 > 标准条款库 > 历史合同
- **10 个行业预设**：建筑、房地产、金融、医药、IT、制造、能源电力、汽车、建工勘察设计、通用商事
- **多种导出格式**：主 CSV、元数据 CSV、冲突报告 HTML、变更集 CSV、摘要 HTML

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+, FastAPI, Uvicorn, aiohttp |
| 前端 | React 18, TypeScript, Vite 5, Tailwind CSS 3 |
| 数据库 | SQLite |
| LLM | DeepSeek / OpenAI 兼容 API |
| 文件解析 | python-docx, pdfplumber, PyMuPDF, openpyxl, lxml |

## 快速开始

### 方式一：在线体验（推荐）

直接访问 [https://rule-harness-demo.onrender.com](https://rule-harness-demo.onrender.com)，无需本地安装即可上传文件并体验完整流程。

当前线上版本基于 Render 部署，配置文件见仓库根目录的 `render.yaml`。

### 方式二：GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/SenryLee/rule-harness?devcontainer_path=.devcontainer%2Fdevcontainer.json)

点击徽章，等待环境启动后访问端口 8765。

### 方式三：本地运行

```bash
git clone https://github.com/SenryLee/rule-harness.git
cd rule-harness
./start.sh
```

浏览器访问 `http://localhost:8765`。

## 项目结构

```
├── backend/                # Python 后端
│   ├── app.py              # FastAPI 入口 + API 路由
│   ├── orchestrator.py     # 批处理编排器
│   ├── pipelines/          # 5 条抽取管线
│   ├── confidence.py       # 五重门置信度评分
│   ├── fidelity.py         # 数值忠实度检测
│   ├── voice_check.py      # 软硬语气检测
│   └── placeholder_detector.py
├── frontend/               # React 前端
│   └── src/
│       ├── App.tsx          # 主应用
│       └── components/      # UI 组件
├── profiles/               # 行业预设 YAML
├── samples/                # 示例文件
├── config.default.yaml     # 默认配置
└── start.sh                # 一键启动
```

## 行业预设

通过配置抽屉选择行业预设，自动调整：
- 行业词表
- 关注要点
- 优先级权重

支持的行业：建筑、房地产、金融、医药、IT、制造、能源电力、汽车、建工勘察设计、通用商事。

## 输出格式

| 文件 | 说明 |
|------|------|
| `rules_main.csv` | 主规则（7 列：启用/风险/关键词/检查项/要求/备注/规则ID） |
| `rules_metadata.csv` | 元数据（置信度、来源、管线、主题键等） |
| `conflict_report.html` | 冲突报告 |
| `change_set.csv` | 变更集 |
| `summary.html` | 处理摘要 |
| `placeholders.csv` | 占位符规则 |
| `discarded.csv` | 丢弃规则 |
| `negotiation.csv` | 谈判规则 |

## License

MIT
