# Design System — 规则梳理 Harness

## Product Context
- **What this is:** AI 驱动的法律合同规则抽取工具，将异构法律材料转化为结构化审查规则
- **Who it's for:** 法务、合规官、合同审查律师
- **Space/industry:** 法律科技 / Legal Tech
- **Project type:** Web 应用（内部专业工具）

## Aesthetic Direction
- **Direction:** Noir Codex — 暗夜法典
- **Decoration level:** intentional — 微妙的金色点缀、卡片光晕、精致的间距节奏
- **Mood:** 专注、权威、沉浸。像在深色阅览室翻开一本烫金封面的法典。专业但不冷酷，现代但不轻浮。
- **One memorable thing:** 琥珀金的微光在暗色背景上，像法典封面的烫金文字

## Typography
| Role | Font | Rationale |
|------|------|-----------|
| Display/Hero | DM Serif Display | 衬线传递权威感，在标题位置建立品牌识别 |
| Body/UI | Inter | 现代无衬线，屏幕可读性极佳，与 DM Serif 形成明确层级对比 |
| Data/Tables | Inter (tabular-nums) | 数字对齐是数据表格的刚需 |
| Code/Mono | JetBrains Mono | 清晰、有性格、连字支持 |
| Chinese fallback | Noto Serif SC (标题) / Noto Sans SC (正文) | 中英文混排优化 |

**Scale:** 12/14/16/18/20/24/30/36/48px

## Color — Noir Codex

### Core Palette
| Token | Hex | Usage |
|-------|-----|-------|
| bg-primary | `#0B1121` | 主背景 — 法典黑，接近黑但有蓝调底蕴 |
| bg-secondary | `#111827` | 次级背景 — 卡片、侧边栏 |
| bg-tertiary | `#1A2332` | 三级背景 — hover、选中态 |
| surface | `#1E293B` | 表面 — 输入框、表格行 |
| border | `#2D3A4A` | 边框 — 微妙但可见 |
| text-primary | `#F1F5F9` | 主文字 — 近白，slate-100 |
| text-secondary | `#94A3B8` | 次级文字 — slate-400 |
| text-muted | `#64748B` | 弱化文字 — slate-500 |

### Accent
| Token | Hex | Usage |
|-------|-----|-------|
| accent | `#F59E0B` | 琥珀金 — 主强调色。CTA、选中态、焦点环、品牌元素 |
| accent-hover | `#D97706` | hover 加深 |
| accent-soft | `#78350F` (20% opacity) | 微妙金色背景 |

### Semantic
| Token | Hex | Usage |
|-------|-----|-------|
| success | `#10B981` | 成功、启用、低风险 |
| warning | `#F59E0B` | 警告、中风险 |
| danger | `#EF4444` | 错误、高风险、删除 |
| info | `#3B82F6` | 信息、链接 |

### Risk Levels (合同审查专用)
| Level | Color | Badge Style |
|-------|-------|-------------|
| 高风险 | `#EF4444` | 红色背景 + 白色文字 |
| 中风险 | `#F59E0B` | 琥珀色背景 + 深色文字 |
| 低风险 | `#10B981` | 绿色背景 + 深色文字 |

## Spacing
- **Base unit:** 4px
- **Density:** comfortable — 法律工具需要清晰的信息层级
- **Scale:** 4/8/12/16/20/24/32/40/48/64px

## Layout
- **Approach:** hybrid — 暗色侧边栏导航 + 网格规整内容区
- **Sidebar:** 240px 宽，深色 (`#0B1121`)，琥珀金 active 指示器
- **Content:** `max-w-7xl` (1280px)，左侧留白充分
- **Border radius:** 分层级 — inputs: 6px, cards: 10px, modals: 14px, buttons: 8px

## Motion
- **Approach:** intentional — 过渡帮助理解状态变化，不分散注意力
- **Easing:** `cubic-bezier(0.4, 0, 0.2, 1)` (ease-out for entering, ease-in for exiting)
- **Duration:** micro 100ms (hover), short 200ms (collapse), medium 350ms (page transitions)

## Component Patterns

### Buttons
- Primary: 琥珀金背景 `bg-accent text-bg-primary`，hover 发光 `shadow-[0_0_20px_rgba(245,158,11,0.15)]`
- Secondary: 透明 + 边框 `border-border text-text-secondary hover:bg-bg-tertiary`
- Danger: `bg-danger/20 text-danger border-danger/30`

### Cards
- `bg-bg-secondary border-border rounded-[10px]`
- hover 时微妙提亮 `hover:bg-bg-tertiary transition-colors`

### Inputs
- `bg-bg-tertiary border-border text-text-primary rounded-[6px]`
- focus: `border-accent ring-1 ring-accent/30`
- placeholder: `text-text-muted`

### Navigation
- 侧边栏: `w-60 bg-bg-primary border-r border-border`
- Active item: `bg-accent/15 text-accent` + 左侧 2px 琥珀金竖线
- Inactive item: `text-text-secondary hover:bg-bg-tertiary hover:text-text-primary`

### Badges
- 使用语义色背景 15% opacity + 同色文字
- 圆角 pill `rounded-full px-2.5 py-0.5 text-xs font-medium`

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-22 | Noir Codex 方向 — 深色默认 + 琥珀金强调 | 用户选择更大胆的设计，法律工具需要权威感而非标准 SaaS 外观 |
| 2026-05-22 | DM Serif Display + Inter 字体组合 | 衬线标题建立品牌权威，无衬线正文保证可读性 |
| 2026-05-22 | 侧边栏导航替代顶部导航 | 深色侧边栏营造沉浸感，释放水平空间给内容 |
