import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  fetchRules,
  fetchBatchRules,
  toggleRuleEnabled,
  downloadExport,
  applyMerge,
  fetchThemes,
  fetchPendingThemes,
  approveThemes,
} from '../api'
import type {
  RuleItem,
  RuleFilters,
  BatchRuleFilters,
  RuleListResponse,
  PendingThemeMapping,
  ThemesResponse,
  PendingThemesResponse,
} from '../api'

/* ════════════════════════════ Props ════════════════════════════ */

interface RulesViewProps {
  batchId: string | null
  refreshKey: number
}

/* ════════════════════════ Sub-components ════════════════════════ */

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    high: 'badge-danger',
    medium: 'badge-warning',
    low: 'badge-success',
  }
  const label: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return <span className={map[level] || 'badge-info'}>{label[level] || level}</span>
}

function ConfidenceBar({ value }: { value?: number }) {
  if (value === undefined || value === null) {
    return <span className="text-gray-400 text-sm">-</span>
  }
  const pct = Math.round(value * 100)
  const color =
    pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-primary' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-gray-200 rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-gray-500 w-8">{pct}%</span>
    </div>
  )
}

function PipelineBadge({ pipeline }: { pipeline?: string }) {
  if (!pipeline) return <span className="text-gray-400 text-sm">-</span>
  return <span className="badge-accent">{pipeline}</span>
}

function ConflictBadge({ flag }: { flag?: string }) {
  if (!flag) return <span className="text-gray-400 text-sm">-</span>
  const map: Record<string, string> = {
    conflict: 'badge-danger',
    variant: 'badge-warning',
    consistent: 'badge-success',
  }
  const label: Record<string, string> = {
    conflict: '冲突',
    variant: '变体',
    consistent: '一致',
  }
  return <span className={map[flag] || 'badge-info'}>{label[flag] || flag}</span>
}

function RuleTypeBadge({ ruleType }: { ruleType?: string }) {
  if (!ruleType) return <span className="text-gray-400 text-sm">-</span>
  const map: Record<string, string> = {
    prohibition: 'badge-accent',
    obligation: 'badge-accent',
    conditional: 'badge-info',
    definition: 'badge-info',
    procedural: 'badge-warning',
  }
  const label: Record<string, string> = {
    prohibition: '禁止性',
    obligation: '义务性',
    conditional: '条件性',
    definition: '定义性',
    procedural: '程序性',
  }
  return <span className={map[ruleType] || 'badge-accent'}>{label[ruleType] || ruleType}</span>
}

function ToggleSwitch({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onChange()
      }}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30 ${
        enabled ? 'bg-primary' : 'bg-gray-300'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform duration-200 ${
          enabled ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

function HighlightedExcerpt({ text, keywords }: { text: string; keywords?: string[] }) {
  const keywordList = keywords ?? []
  const parts = useMemo(() => {
    if (keywordList.length === 0) return null
    const escaped = keywordList.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
    return text.split(pattern)
  }, [text, keywordList])

  if (!parts) return <>{text}</>

  return (
    <>
      {parts.map((part, i) => {
        const isMatch = keywordList.some((k) => k.toLowerCase() === part.toLowerCase())
        return isMatch ? (
          <mark key={i} className="bg-amber-100 text-amber-800 rounded-sm px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      })}
    </>
  )
}

function LadderDisplay({ rule }: { rule: RuleItem }) {
  const tiers = [
    { label: '首选', value: rule.ladder_preferred, color: 'bg-emerald-500' },
    { label: '可接受', value: rule.ladder_acceptable, color: 'bg-amber-500' },
    { label: '不可接受', value: rule.ladder_unacceptable, color: 'bg-red-500' },
  ].filter((t) => t.value)

  if (tiers.length === 0) {
    if (!rule.ladder_info) return null
    return (
      <pre className="text-xs text-gray-600 bg-gray-50 p-3 rounded-input overflow-x-auto border border-air-border">
        {JSON.stringify(rule.ladder_info, null, 2)}
      </pre>
    )
  }

  return (
    <div className="space-y-3">
      {tiers.map((item) => (
        <div key={item.label} className="flex gap-3">
          <div
            className={`w-1 self-stretch rounded-full flex-shrink-0 ${item.color}`}
          />
          <div>
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-0.5">
              {item.label}
            </div>
            <div className="text-sm text-gray-900 whitespace-pre-wrap">
              {item.value}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function CitedCasesDisplay({ cases }: { cases?: unknown[] }) {
  if (!cases || cases.length === 0) return null
  return (
    <div className="space-y-3">
      {cases.map((c, i) => {
        let text: string
        if (typeof c === 'string') {
          text = c
        } else if (typeof c === 'object' && c !== null) {
          const obj = c as Record<string, unknown>
          text = String(obj.description || obj.text || obj.case_name || JSON.stringify(c))
        } else {
          text = String(c)
        }
        return (
          <blockquote
            key={i}
            className="border-l-2 border-primary pl-4 py-1 text-sm text-gray-600 italic"
          >
            {text}
          </blockquote>
        )
      })}
    </div>
  )
}

/* ═══════════════════════ Main Component ═══════════════════════ */

export default function RulesView({ batchId, refreshKey }: RulesViewProps) {
  /* ─── Common state ─── */
  const [rules, setRules] = useState<RuleItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRule, setSelectedRule] = useState<RuleItem | null>(null)

  /* ─── Master mode state ─── */
  const [themes, setThemes] = useState<string[]>([])
  const [pendingThemes, setPendingThemes] = useState<PendingThemeMapping[]>([])
  const [showThemeManager, setShowThemeManager] = useState(false)

  const [masterFilters, setMasterFilters] = useState<RuleFilters>({
    risk_level: '',
    rule_type: '',
    theme_key: '',
    contract_type: '',
    enabled: undefined,
    search: '',
  })

  /* ─── Batch mode state ─── */
  const [applying, setApplying] = useState(false)

  const [batchFilters, setBatchFilters] = useState<BatchRuleFilters>({
    risk_level: '',
    pipeline: '',
    confidence_min: undefined,
    confidence_max: undefined,
    conflict_flag: '',
    contract_type: '',
    source_file: '',
  })

  const isBatchMode = batchId !== null

  /* ─── Data fetching ─── */

  useEffect(() => {
    if (!isBatchMode) {
      let cancelled = false
      setLoading(true)
      setError(null)
      const filters: RuleFilters = { ...masterFilters, page, page_size: pageSize }
      // clean empty strings
      Object.keys(filters).forEach((k) => {
        const key = k as keyof RuleFilters
        if (filters[key] === '' || filters[key] === undefined) {
          delete filters[key]
        }
      })
      fetchRules(filters)
        .then((res: RuleListResponse) => {
          if (!cancelled) {
            setRules(res.rules)
            setTotal(res.total)
          }
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message)
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => {
        cancelled = true
      }
    }
  }, [isBatchMode, masterFilters, page, pageSize, refreshKey])

  useEffect(() => {
    if (isBatchMode && batchId) {
      let cancelled = false
      setLoading(true)
      setError(null)
      const filters: BatchRuleFilters = { ...batchFilters, page, page_size: pageSize }
      Object.keys(filters).forEach((k) => {
        const key = k as keyof BatchRuleFilters
        if (filters[key] === '' || filters[key] === undefined) {
          delete filters[key]
        }
      })
      fetchBatchRules(batchId, filters)
        .then((res: RuleListResponse) => {
          if (!cancelled) {
            setRules(res.rules)
            setTotal(res.total)
          }
        })
        .catch((err: Error) => {
          if (!cancelled) setError(err.message)
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => {
        cancelled = true
      }
    }
  }, [isBatchMode, batchId, batchFilters, page, pageSize, refreshKey])

  /* ─── Master: load themes ─── */

  useEffect(() => {
    if (!isBatchMode) {
      fetchThemes()
        .then((res: ThemesResponse) => setThemes(res.keys || []))
        .catch(() => {})
      fetchPendingThemes()
        .then((res: PendingThemesResponse) => setPendingThemes(res.mappings || []))
        .catch(() => {})
    }
  }, [isBatchMode, refreshKey])

  /* ─── Filter change handlers ─── */

  const handleMasterFilterChange = useCallback(
    (key: keyof RuleFilters, value: string | boolean | undefined) => {
      setMasterFilters((prev: RuleFilters) => {
        const next = { ...prev, [key]: value === '' ? undefined : value }
        return next
      })
      setPage(1)
    },
    [],
  )

  const handleBatchFilterChange = useCallback(
    (key: keyof BatchRuleFilters, value: string | number | undefined) => {
      setBatchFilters((prev: BatchRuleFilters) => {
        const next = { ...prev, [key]: value === '' ? undefined : value }
        return next
      })
      setPage(1)
    },
    [],
  )

  /* ─── Toggle enabled ─── */

  const handleToggleEnabled = useCallback(async (rule: RuleItem) => {
    try {
      await toggleRuleEnabled(rule.rule_id, !rule.enabled)
      setRules((prev) =>
        prev.map((r) => (r.rule_id === rule.rule_id ? { ...r, enabled: !r.enabled } : r)),
      )
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }, [])

  /* ─── Theme approval ─── */

  const handleApproveThemes = useCallback(async () => {
    const mappings = pendingThemes.map((m) => ({
      rule_id: m.rule_id,
      approved_theme: m.suggested_theme,
    }))
    try {
      await approveThemes(mappings)
      setPendingThemes([])
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }, [pendingThemes])

  /* ─── Batch apply ─── */

  const handleApplyMerge = useCallback(async () => {
    if (!batchId || !confirm('确认将本批次规则合并到主规则库？此操作不可撤销。')) return
    setApplying(true)
    try {
      await applyMerge(batchId)
      alert('已成功合并到主规则库')
    } catch (err) {
      alert(err instanceof Error ? err.message : '合并失败')
    } finally {
      setApplying(false)
    }
  }, [batchId])

  /* ─── Computed ─── */

  const totalPages = Math.ceil(total / pageSize)

  // Compute batch summary stats from the rules array for batch mode
  const batchSummary = useMemo(() => {
    if (!isBatchMode) return null
    const high = rules.filter((r) => r.risk_level === 'high').length
    const medium = rules.filter((r) => r.risk_level === 'medium').length
    const low = rules.filter((r) => r.risk_level === 'low').length
    const needsReview = rules.filter(
      (r) => r.conflict_flag === 'conflict' || r.conflict_flag === 'variant',
    ).length
    const conflicts = rules.filter((r) => r.conflict_flag === 'conflict').length
    return {
      total: total,
      high,
      medium,
      low,
      needsReview,
      conflicts,
    }
  }, [isBatchMode, rules, total])

  /* ─── Clear all batch filters ─── */

  const clearBatchFilters = useCallback(() => {
    setBatchFilters({
      risk_level: '',
      pipeline: '',
      confidence_min: undefined,
      confidence_max: undefined,
      conflict_flag: '',
      contract_type: '',
      source_file: '',
    })
    setPage(1)
  }, [])

  /* ─── Loading state ─── */

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 animate-fade-in">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-air-border border-t-primary" />
        <span className="text-gray-400 text-sm">
          {isBatchMode ? '加载报告数据...' : '加载规则数据...'}
        </span>
      </div>
    )
  }

  /* ─── Error state ─── */

  if (error) {
    return (
      <div className="card p-6 border-red-200 bg-red-50 animate-fade-in">
        <div className="flex items-start gap-3">
          <svg
            className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
            />
          </svg>
          <div>
            <div className="text-sm font-semibold text-red-600">加载失败</div>
            <div className="text-sm text-gray-600 mt-1">{error}</div>
          </div>
        </div>
      </div>
    )
  }

  /* ══════════════════ Master Rule Library Mode ══════════════════ */

  if (!isBatchMode) {
    return (
      <div className="animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="font-display text-2xl text-gray-900 pb-2">规则管理</h1>
          {pendingThemes.length > 0 && (
            <button
              type="button"
              onClick={() => setShowThemeManager(!showThemeManager)}
              className="btn-secondary text-sm"
            >
              主题审核 ({pendingThemes.length})
            </button>
          )}
        </div>

        {/* Pending theme banner */}
        {showThemeManager && pendingThemes.length > 0 && (
          <div className="card p-4 mb-6 border-l-2 border-primary">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-body text-base font-semibold text-gray-900">待审核主题</h3>
              <button type="button" onClick={handleApproveThemes} className="btn-primary text-sm">
                全部确认
              </button>
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {pendingThemes.map((m) => (
                <div
                  key={m.rule_id}
                  className="flex items-center justify-between py-2 px-3 bg-air-muted rounded-lg"
                >
                  <div className="text-sm font-mono text-gray-500">{m.rule_id}</div>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-gray-400">{m.current_theme || '(空)'}</span>
                    <span className="text-gray-400">→</span>
                    <span className="text-primary font-medium">{m.suggested_theme}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filter bar */}
        <div className="card px-4 py-3 mb-6">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">风险级别</label>
              <select
                value={masterFilters.risk_level || ''}
                onChange={(e) => handleMasterFilterChange('risk_level', e.target.value)}
                className="select-field text-xs"
              >
                <option value="">全部</option>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">规则类型</label>
              <select
                value={masterFilters.rule_type || ''}
                onChange={(e) => handleMasterFilterChange('rule_type', e.target.value)}
                className="select-field text-xs"
              >
                <option value="">全部</option>
                <option value="prohibition">禁止性</option>
                <option value="obligation">义务性</option>
                <option value="conditional">条件性</option>
                <option value="definition">定义性</option>
                <option value="procedural">程序性</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">主题</label>
              <select
                value={masterFilters.theme_key || ''}
                onChange={(e) => handleMasterFilterChange('theme_key', e.target.value)}
                className="select-field text-xs"
              >
                <option value="">全部</option>
                {themes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">合同类型</label>
              <select
                value={masterFilters.contract_type || ''}
                onChange={(e) => handleMasterFilterChange('contract_type', e.target.value)}
                className="select-field text-xs"
              >
                <option value="">全部</option>
                {['采购', '销售', '服务', '保密', '技术', '许可', '租赁', '劳动', '通用商事'].map(
                  (ct) => (
                    <option key={ct} value={ct}>
                      {ct}
                    </option>
                  ),
                )}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">状态</label>
              <select
                value={
                  masterFilters.enabled === undefined
                    ? ''
                    : masterFilters.enabled
                      ? 'true'
                      : 'false'
                }
                onChange={(e) => {
                  const val = e.target.value
                  handleMasterFilterChange(
                    'enabled',
                    val === '' ? undefined : val === 'true',
                  )
                }}
                className="select-field text-xs"
              >
                <option value="">全部</option>
                <option value="true">已启用</option>
                <option value="false">已禁用</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">搜索</label>
              <input
                type="text"
                value={masterFilters.search || ''}
                onChange={(e) => handleMasterFilterChange('search', e.target.value)}
                placeholder="检查项、要求..."
                className="input-field text-xs"
              />
            </div>
          </div>
        </div>

        {/* Rule table */}
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-air-border bg-gray-50/50">
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    规则ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    状态
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    风险
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    检查项
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium max-w-xs">
                    审查要求
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    管道
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    置信度
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase tracking-wider font-medium">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {rules.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-10 text-center text-gray-400">
                      暂无规则数据
                    </td>
                  </tr>
                ) : (
                  rules.map((rule) => (
                    <tr
                      key={rule.rule_id}
                      className="border-b border-air-border hover:bg-air-hover transition-colors"
                    >
                      <td className="px-4 py-3 text-sm font-mono text-gray-500 whitespace-nowrap">
                        {rule.rule_id}
                      </td>
                      <td className="px-4 py-3">
                        <ToggleSwitch
                          enabled={rule.enabled === true || rule.enabled === '启用'}
                          onChange={() => handleToggleEnabled(rule)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <RiskBadge level={rule.risk_level} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                        {rule.check_item}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">
                        {rule.requirement}
                      </td>
                      <td className="px-4 py-3">
                        <PipelineBadge pipeline={rule.pipeline} />
                      </td>
                      <td className="px-4 py-3">
                        <ConfidenceBar value={rule.combined_confidence ?? rule.confidence} />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedRule(rule)
                          }}
                          className="text-primary hover:text-primary-hover text-sm font-medium transition-colors"
                        >
                          详情
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-air-border">
              <div className="text-sm text-gray-400">
                共 {total} 条，第 {page} / {totalPages} 页
              </div>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="btn-secondary text-xs py-1 px-3"
                >
                  上一页
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="btn-secondary text-xs py-1 px-3"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Detail drawer */}
        {selectedRule && (
          <DetailDrawer rule={selectedRule} onClose={() => setSelectedRule(null)} />
        )}
      </div>
    )
  }

  /* ══════════════════ Batch Report Mode ════════════════════════ */

  return (
    <div className="animate-fade-in pb-24">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl text-gray-900">批次报告</h1>
          <div className="font-mono text-sm text-gray-400 mt-1">{batchId}</div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-4 mb-6">
        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-gray-900">
            {batchSummary?.total ?? total}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">总规则数</div>
        </div>
        <div className="card p-5 text-center border-l-2 border-l-red-500">
          <div className="font-mono text-3xl font-bold text-red-500">
            {batchSummary?.high ?? 0}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">高风险</div>
        </div>
        <div className="card p-5 text-center border-l-2 border-l-amber-500">
          <div className="font-mono text-3xl font-bold text-amber-500">
            {batchSummary?.medium ?? 0}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">中风险</div>
        </div>
        <div className="card p-5 text-center border-l-2 border-l-emerald-500">
          <div className="font-mono text-3xl font-bold text-emerald-500">
            {batchSummary?.low ?? 0}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">低风险</div>
        </div>
        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-gray-900">
            {batchSummary?.needsReview ?? 0}
          </div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">需复核</div>
        </div>
        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-gray-400">-</div>
          <div className="text-xs text-gray-400 uppercase tracking-wider mt-1">Token消耗</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="card p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">风险级别</label>
            <select
              value={batchFilters.risk_level || ''}
              onChange={(e) => handleBatchFilterChange('risk_level', e.target.value)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">管道</label>
            <select
              value={batchFilters.pipeline || ''}
              onChange={(e) => handleBatchFilterChange('pipeline', e.target.value)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
              <option value="P3">P3</option>
              <option value="P4">P4</option>
              <option value="P5">P5</option>
              <option value="direct">direct</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">冲突标记</label>
            <select
              value={batchFilters.conflict_flag || ''}
              onChange={(e) => handleBatchFilterChange('conflict_flag', e.target.value)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="conflict">冲突</option>
              <option value="variant">变体</option>
              <option value="consistent">一致</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">合同类型</label>
            <select
              value={batchFilters.contract_type || ''}
              onChange={(e) => handleBatchFilterChange('contract_type', e.target.value)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              {['采购', '销售', '服务', '保密', '技术', '许可', '租赁', '劳动', '通用商事'].map(
                (ct) => (
                  <option key={ct} value={ct}>
                    {ct}
                  </option>
                ),
              )}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">来源文件</label>
            <select
              value={batchFilters.source_file || ''}
              onChange={(e) => handleBatchFilterChange('source_file', e.target.value)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              置信度: {batchFilters.confidence_min ?? 0} - {batchFilters.confidence_max ?? 1}
            </label>
            <div className="flex gap-2">
              <input
                type="number"
                value={batchFilters.confidence_min ?? ''}
                onChange={(e) =>
                  handleBatchFilterChange(
                    'confidence_min',
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
                min={0}
                max={1}
                step={0.1}
                placeholder="0"
                className="input-field text-xs w-16"
              />
              <span className="text-gray-400 text-xs self-center">-</span>
              <input
                type="number"
                value={batchFilters.confidence_max ?? ''}
                onChange={(e) =>
                  handleBatchFilterChange(
                    'confidence_max',
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
                min={0}
                max={1}
                step={0.1}
                placeholder="1"
                className="input-field text-xs w-16"
              />
            </div>
          </div>
        </div>

        {/* Clear all filter button */}
        {(batchFilters.risk_level ||
          batchFilters.pipeline ||
          batchFilters.conflict_flag ||
          batchFilters.contract_type ||
          batchFilters.source_file ||
          batchFilters.confidence_min !== undefined ||
          batchFilters.confidence_max !== undefined) && (
          <div className="mt-3 pt-3 border-t border-air-border flex justify-end">
            <button
              type="button"
              onClick={clearBatchFilters}
              className="btn-ghost text-xs"
            >
              清除全部筛选
            </button>
          </div>
        )}
      </div>

      {/* Rule table */}
      <div className="card overflow-hidden mb-6">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-air-border">
            <thead>
              <tr className="bg-gray-50/50">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  规则ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  风险
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  检查项
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider max-w-xs">
                  审查要求
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  管道
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  置信度
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  冲突
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-air-border">
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-gray-400">
                    暂无规则数据
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr
                    key={rule.rule_id}
                    className="hover:bg-air-hover cursor-pointer transition-colors"
                    onClick={() => setSelectedRule(rule)}
                  >
                    <td className="px-4 py-3 text-sm font-mono text-gray-400 whitespace-nowrap">
                      {rule.rule_id}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={rule.risk_level} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                      {rule.check_item}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">
                      {rule.requirement}
                    </td>
                    <td className="px-4 py-3">
                      <PipelineBadge pipeline={rule.pipeline} />
                    </td>
                    <td className="px-4 py-3">
                      <ConfidenceBar value={rule.combined_confidence ?? rule.confidence} />
                    </td>
                    <td className="px-4 py-3">
                      <ConflictBadge flag={rule.conflict_flag} />
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          setSelectedRule(rule)
                        }}
                        className="text-primary hover:text-primary-hover text-sm font-medium transition-colors"
                      >
                        详情
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-air-border">
            <div className="text-sm text-gray-400">
              共 {total} 条，第 {page} / {totalPages} 页
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="btn-secondary text-xs py-1 px-3"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="btn-secondary text-xs py-1 px-3"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Sticky bottom action bar */}
      <div className="sticky bottom-0 z-20 bg-white/90 backdrop-blur-sm border border-air-border rounded-card shadow-popover px-6 py-3 flex items-center justify-between mt-6">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 mr-2">导出:</span>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'main-csv')}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            主CSV
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'metadata-csv')}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            元数据CSV
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'conflict-report')}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            冲突报告HTML
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'change-set')}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            变更集CSV
          </button>
        </div>
        <button
          type="button"
          onClick={handleApplyMerge}
          disabled={applying}
          className="btn-primary text-sm"
        >
          {applying ? '合并中...' : '应用变更入库'}
        </button>
      </div>

      {/* Detail drawer */}
      {selectedRule && (
        <DetailDrawer rule={selectedRule} onClose={() => setSelectedRule(null)} />
      )}
    </div>
  )
}

/* ═════════════════════ Detail Drawer ════════════════════════ */

function DetailDrawer({ rule, onClose }: { rule: RuleItem; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-fade-in">
      {/* Overlay */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-[520px] bg-white shadow-xl overflow-y-auto h-full animate-slide-in">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-air-border px-6 py-4 flex items-center justify-between">
          <h3 className="font-display text-lg text-gray-900">规则详情</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-btn hover:bg-air-hover"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-5">
          {/* ── Section: Basic Info ── */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-gray-400 mb-0.5">规则ID</div>
              <div className="text-sm font-mono text-gray-900">{rule.rule_id}</div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">风险级别</div>
              <RiskBadge level={rule.risk_level} />
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">状态</div>
              <div className={rule.enabled ? 'text-emerald-600 text-sm font-medium' : 'text-gray-400 text-sm'}>
                {rule.enabled ? '已启用' : '已禁用'}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">管道</div>
              <PipelineBadge pipeline={rule.pipeline} />
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">版本</div>
              <div className="text-sm text-gray-900">v{rule.version || 1}</div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">规则类型</div>
              <RuleTypeBadge ruleType={rule.rule_type} />
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">合同类型</div>
              <div className="text-sm text-gray-600">
                {rule.contract_types?.join(', ') || '-'}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-400 mb-0.5">冲突状态</div>
              <ConflictBadge flag={rule.conflict_flag} />
            </div>
            {rule.struct_check_pass !== undefined && (
              <div>
                <div className="text-xs text-gray-400 mb-0.5">结构校验</div>
                <span className={rule.struct_check_pass ? 'badge-success' : 'badge-danger'}>
                  {rule.struct_check_pass ? '通过' : '未通过'}
                </span>
              </div>
            )}
          </div>

          {/* ── Keywords ── */}
          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-1.5">关键词</div>
            <div className="flex flex-wrap gap-1.5">
              {rule.keywords?.length > 0 ? (
                rule.keywords.map((kw: string, i: number) => (
                  <span
                    key={i}
                    className="inline-flex px-2 py-0.5 rounded text-xs bg-primary-light text-primary font-medium"
                  >
                    {kw}
                  </span>
                ))
              ) : (
                <span className="text-sm text-gray-400">-</span>
              )}
            </div>
          </div>

          {/* ── Section: Check Item & Requirement ── */}
          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-1.5">检查项</div>
            <div className="text-sm text-gray-900 whitespace-pre-wrap leading-relaxed">
              {rule.check_item}
            </div>
          </div>

          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-1.5">审查要求</div>
            <div className="text-sm text-gray-900 whitespace-pre-wrap leading-relaxed">
              {rule.requirement}
            </div>
          </div>

          {/* Notes */}
          {rule.notes && (
            <div className="pt-4 border-t border-air-border">
              <div className="text-xs text-gray-400 mb-1.5">备注</div>
              <div className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">
                {rule.notes}
              </div>
            </div>
          )}

          {/* ── Section: Source ── */}
          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-1.5">来源信息</div>
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-gray-400">文件: </span>
                  <span className="text-gray-600 font-mono">
                    {rule.source_filename || rule.source_file || '-'}
                  </span>
                </div>
                <div>
                  <span className="text-gray-400">位置: </span>
                  <span className="text-gray-600 font-mono">{rule.source_location || '-'}</span>
                </div>
              </div>
            </div>
          </div>

          {rule.source_excerpt && (
            <div className="pt-4 border-t border-air-border">
              <div className="text-xs text-gray-400 mb-1.5">原文摘录</div>
              <div className="bg-air-muted rounded-input p-4 text-sm text-gray-700 leading-relaxed border border-air-border">
                <HighlightedExcerpt text={rule.source_excerpt} keywords={rule.keywords} />
              </div>
            </div>
          )}

          {/* ── Section: Metadata ── */}
          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-2">元数据</div>
            <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-sm">
              <div>
                <span className="text-gray-400">模型: </span>
                <span className="text-gray-600">{rule.model || '-'}</span>
              </div>
              <div>
                <span className="text-gray-400">主题: </span>
                <span className="text-gray-600">{rule.theme_key || '-'}</span>
              </div>
              <div>
                <span className="text-gray-400">方向: </span>
                <span className="text-gray-600">{rule.direction || '-'}</span>
              </div>
              <div>
                <span className="text-gray-400">主体: </span>
                <span className="text-gray-600">{rule.subject || '-'}</span>
              </div>
              <div>
                <span className="text-gray-400">谓词: </span>
                <span className="text-gray-600">{rule.predicate || '-'}</span>
              </div>
              <div>
                <span className="text-gray-400">阈值类型: </span>
                <span className="text-gray-600">{rule.threshold_type || '-'}</span>
              </div>
              {rule.first_batch_id && (
                <div>
                  <span className="text-gray-400">首批: </span>
                  <span className="text-gray-600 font-mono text-xs">{rule.first_batch_id}</span>
                </div>
              )}
              {rule.last_batch_id && (
                <div>
                  <span className="text-gray-400">末批: </span>
                  <span className="text-gray-600 font-mono text-xs">{rule.last_batch_id}</span>
                </div>
              )}
            </div>
          </div>

          {/* Confidence breakdown */}
          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-2">置信度明细</div>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">综合置信度</span>
                <ConfidenceBar value={rule.combined_confidence ?? rule.confidence} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">自身置信度</span>
                <ConfidenceBar value={rule.confidence_self} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">一致性</span>
                <ConfidenceBar value={rule.confidence_consistency} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">结构化</span>
                <ConfidenceBar value={rule.confidence_struct} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">冲突检测</span>
                <ConfidenceBar value={rule.confidence_conflict} />
              </div>
            </div>
          </div>

          {/* ── Section: Ladder Info ── */}
          {(rule.ladder_info ||
            rule.ladder_preferred ||
            rule.ladder_acceptable ||
            rule.ladder_unacceptable) && (
            <div className="pt-4 border-t border-air-border">
              <div className="text-xs text-gray-400 mb-1.5">阶梯信息 (Ladder)</div>
              <LadderDisplay rule={rule} />
            </div>
          )}

          {/* ── Section: Cited Cases ── */}
          {rule.cited_cases && rule.cited_cases.length > 0 && (
            <div className="pt-4 border-t border-air-border">
              <div className="text-xs text-gray-400 mb-1.5">引用案例</div>
              <CitedCasesDisplay cases={rule.cited_cases} />
            </div>
          )}

          {/* ── Section: Variants ── */}
          {rule.variants && rule.variants.length > 0 && (
            <div className="pt-4 border-t border-air-border">
              <div className="text-xs text-gray-400 mb-1.5">变体版本</div>
              <pre className="text-xs text-gray-600 bg-gray-50 p-3 rounded-input overflow-x-auto border border-air-border">
                {JSON.stringify(rule.variants, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
