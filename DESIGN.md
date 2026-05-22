# Design System — 规则梳理 Harness

## Product Context
- **What this is:** AI 驱动的法律合同规则抽取工具
- **Who it's for:** 法务、合规官、合同审查律师
- **Space/industry:** 法律科技
- **Project type:** 单页 Web 应用

## Aesthetic Direction
- **Direction:** Air Legal — 清亮、专业、高效
- **Mood:** 白色底色营造干净、值得信赖的专业感；浅蓝点缀传递科技与精准；单页布局让所有操作流畅无跳转

## Typography
| Role | Font | Rationale |
|------|------|-----------|
| Display/Body | Inter | 现代无衬线，屏幕可读性极佳 |
| Code/Data | JetBrains Mono | 清晰、连字支持 |
| Chinese fallback | Noto Sans SC | 中英文混排优化 |

## Color — Air Legal
### Core
| Token | Hex | Usage |
|-------|-----|-------|
| bg | `#FFFFFF` | 主背景 |
| bg-muted | `#F8FAFC` | 页面底色 |
| bg-hover | `#F1F5F9` | hover 态 |
| border | `#E2E8F0` | 默认边框 |
| border-accent | `#BFDBFE` | 蓝色边框 |
| text-primary | `#0F172A` | 主文字 |
| text-secondary | `#475569` | 副文字 |
| text-muted | `#94A3B8` | 弱文字 |

### Primary (Blue)
| Token | Hex | Usage |
|-------|-----|-------|
| primary | `#2563EB` | 主按钮、链接、选中态 |
| primary-hover | `#3B82F6` | hover 加深 |
| primary-light | `#DBEAFE` | 选中背景 |
| primary-soft | `#EFF6FF` | 微妙蓝底 |

### Accent (Sky)
| Token | Hex | Usage |
|-------|-----|-------|
| accent | `#0EA5E9` | 次要强调 |
| accent-hover | `#38BDF8` | hover |
| accent-light | `#E0F2FE` | 微妙天蓝底 |

### Semantic
| Token | Usage |
|-------|-------|
| red (bg-red-100, text-red-700) | 高风险、错误 |
| amber (bg-amber-100, text-amber-700) | 中风险、警告 |
| emerald (bg-emerald-100, text-emerald-700) | 低风险、成功 |
| blue (bg-blue-100, text-blue-700) | 信息 |
| sky (bg-sky-100, text-sky-700) | 管道标记 |

## Layout
- **Structure:** Header (h-14, fixed) + 双栏（左 320px TaskPanel + 右 RulesView）
- **Single page:** 状态驱动视图切换，无路由跳转
- **Config:** 全屏右侧抽屉（560px）
- **Detail:** 右侧滑入面板（520px）
- **Max content width:** 自适应

## Spacing
- **Base unit:** 8px
- **Card padding:** 16-24px
- **Section gap:** 16-24px

## Motion
- **Easing:** ease-out for entering, ease-in for exiting
- **Duration:** 150ms micro, 250ms panel slide, 200ms fade
- **Drawers:** slide-in from right (translateX 16px → 0)

## Components
- `btn-primary` — blue bg, white text, hover darken
- `btn-secondary` — white bg, gray border, hover blue border
- `btn-danger` — red tint
- `btn-ghost` — text only
- `card` — white bg, light border, subtle shadow
- `input-field` / `select-field` — white bg, gray border, blue focus ring
- `badge-*` — colored bg pills

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-22 | Air Legal 白色+浅蓝设计系统 | 用户要求白底浅蓝，单页布局 |
| 2026-05-22 | 单页状态驱动替代多页路由 | 所有操作一页完成，提升效率 |
| 2026-05-22 | 双栏布局（任务+规则） | 左侧操作、右侧查看，减少切换 |
