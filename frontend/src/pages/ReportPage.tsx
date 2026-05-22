import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import {
  fetchBatch,
  fetchBatchRules,
  downloadExport,
  applyMerge,
} from '../api'
import type { Batch, RuleItem, BatchRuleFilters } from '../api'

/* ──────────────── Sub-components ──────────────── */

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    high: 'badge-danger',
    medium: 'badge-warning',
    low: 'badge-success',
  }
  const label: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
  }
  return (
    <span className={map[level] || 'badge-info'}>
      {label[level] || level}
    </span>
  )
}

function PipelineBadge({ pipeline }: { pipeline?: string }) {
  if (!pipeline) return <span className="text-codex-text-muted text-sm">-</span>
  const map: Record<string, string> = {
    P1: 'badge-accent',
    P5: 'badge-accent',
    direct: 'badge-info',
  }
  return (
    <span className={map[pipeline] || 'badge-info'}>
      {pipeline}
    </span>
  )
}

function ConflictBadge({ flag }: { flag?: string }) {
  if (!flag) return null
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
  return (
    <span className={map[flag] || 'badge-info'}>
      {label[flag] || flag}
    </span>
  )
}

function ConfidenceBar({ value }: { value?: number }) {
  if (value === undefined || value === null)
    return <span className="text-codex-text-muted text-sm">-</span>
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 bg-codex-bg-tertiary rounded-full h-1.5">
        <div
          className="bg-accent h-1.5 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-codex-text-muted w-8">{pct}%</span>
    </div>
  )
}

function HighlightedExcerpt({
  text,
  keywords,
}: {
  text: string
  keywords?: string[]
}) {
  const keywordList = keywords ?? []
  const parts = useMemo(() => {
    if (keywordList.length === 0) return null
    const escaped = keywordList.map((k) =>
      k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'),
    )
    const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
    return text.split(pattern)
  }, [text, keywordList])

  if (!parts) return <>{text}</>

  return (
    <>
      {parts.map((part, i) => {
        const isMatch = keywordList.some(
          (k) => k.toLowerCase() === part.toLowerCase(),
        )
        return isMatch ? (
          <mark
            key={i}
            className="bg-amber-500/25 text-amber-200 rounded-sm px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      })}
    </>
  )
}

function LadderDisplay({ ladderInfo }: { ladderInfo: unknown }) {
  let tiers: { preferred?: string; acceptable?: string; unacceptable?: string } | null = null

  if (ladderInfo && typeof ladderInfo === 'object' && !Array.isArray(ladderInfo)) {
    const obj = ladderInfo as Record<string, unknown>
    tiers = {
      preferred: typeof obj.preferred === 'string' ? obj.preferred : undefined,
      acceptable: typeof obj.acceptable === 'string' ? obj.acceptable : undefined,
      unacceptable: typeof obj.unacceptable === 'string' ? obj.unacceptable : undefined,
    }
  }

  if (!tiers || (!tiers.preferred && !tiers.acceptable && !tiers.unacceptable)) {
    return (
      <pre className="text-xs text-codex-text-secondary bg-codex-bg-tertiary p-3 rounded-input overflow-x-auto">
        {JSON.stringify(ladderInfo, null, 2)}
      </pre>
    )
  }

  const items = [
    { label: '首选', value: tiers.preferred, color: 'bg-emerald-500' },
    { label: '可接受', value: tiers.acceptable, color: 'bg-amber-500' },
    { label: '不可接受', value: tiers.unacceptable, color: 'bg-red-500' },
  ].filter((i) => i.value)

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.label} className="flex gap-3">
          <div className="flex items-start gap-2.5 flex-1">
            <div
              className={`w-1 self-stretch rounded-full flex-shrink-0 ${item.color}`}
            />
            <div>
              <div className="text-xs font-medium text-codex-text-muted uppercase tracking-wider mb-0.5">
                {item.label}
              </div>
              <div className="text-sm text-codex-text-primary whitespace-pre-wrap">
                {item.value}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function CitedCasesDisplay({ cases }: { cases: unknown[] }) {
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
            className="border-l-2 border-accent pl-4 py-1 text-sm text-codex-text-secondary italic"
          >
            {text}
          </blockquote>
        )
      })}
    </div>
  )
}

/* ──────────────── Page ──────────────── */

export default function ReportPage() {
  const { batchId } = useParams<{ batchId: string }>()
  const [batch, setBatch] = useState<Batch | null>(null)
  const [rules, setRules] = useState<RuleItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRule, setSelectedRule] = useState<RuleItem | null>(null)
  const [applying, setApplying] = useState(false)

  const [filters, setFilters] = useState<BatchRuleFilters>({
    risk_level: '',
    pipeline: '',
    conflict_flag: '',
    contract_type: '',
    source_file: '',
    confidence_min: undefined,
    confidence_max: undefined,
    page: 1,
    page_size: 50,
  })

  useEffect(() => {
    if (!batchId) return
    let cancelled = false
    setLoading(true)
    fetchBatch(batchId)
      .then((b) => {
        if (!cancelled) setBatch(b)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [batchId])

  useEffect(() => {
    if (!batchId) return
    let cancelled = false
    fetchBatchRules(batchId, { ...filters, page, page_size: pageSize })
      .then((res) => {
        if (!cancelled) {
          setRules(res.rules)
          setTotal(res.total)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [batchId, filters, page, pageSize])

  const handleFilterChange = useCallback(
    (key: keyof BatchRuleFilters, value: string | number | undefined) => {
      setFilters((prev) => {
        const next = { ...prev, [key]: value || undefined }
        if (key !== 'page' && key !== 'page_size') {
          next.page = 1
        }
        return next
      })
      setPage(1)
    },
    [],
  )

  const handleApply = useCallback(async () => {
    if (!batchId || !confirm('确认将本批次规则合并到主规则库？此操作不可撤销。'))
      return
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

  const totalPages = Math.ceil(total / pageSize)

  /* ─── active filter definitions ─── */
  const activeFilters = useMemo(() => {
    const items: { key: string; label: string; value: string }[] = []
    if (filters.risk_level) {
      const labels: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
      items.push({ key: 'risk_level', label: '风险', value: labels[filters.risk_level] || filters.risk_level })
    }
    if (filters.pipeline) {
      items.push({ key: 'pipeline', label: '管道', value: filters.pipeline })
    }
    if (filters.conflict_flag) {
      const labels: Record<string, string> = { conflict: '冲突', variant: '变体', consistent: '一致' }
      items.push({ key: 'conflict_flag', label: '冲突', value: labels[filters.conflict_flag] || filters.conflict_flag })
    }
    if (filters.contract_type) {
      items.push({ key: 'contract_type', label: '合同类型', value: filters.contract_type })
    }
    if (filters.source_file) {
      items.push({ key: 'source_file', label: '来源', value: filters.source_file })
    }
    if (filters.confidence_min !== undefined || filters.confidence_max !== undefined) {
      const lo = filters.confidence_min ?? 0
      const hi = filters.confidence_max ?? 1
      items.push({ key: 'confidence', label: '置信度', value: `${lo} - ${hi}` })
    }
    return items
  }, [filters])

  /* ─── Edge states ─── */

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 animate-fade-in">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-codex-border border-t-accent" />
        <span className="text-codex-text-muted">加载报告数据...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card p-6 border-red-500/25 bg-red-500/5 animate-fade-in">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div>
            <div className="text-sm font-semibold text-red-400">加载失败</div>
            <div className="text-sm text-codex-text-secondary mt-1">{error}</div>
          </div>
        </div>
      </div>
    )
  }

  if (!batch) {
    return (
      <div className="flex items-center justify-center py-20 animate-fade-in">
        <span className="text-codex-text-muted">批次不存在</span>
      </div>
    )
  }

  const stats = batch.stats || {}

  return (
    <div className="animate-fade-in pb-24">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl text-codex-text-primary">批次报告</h1>
          <div className="font-mono text-sm text-codex-text-muted mt-1">{batchId}</div>
        </div>
      </div>

      {/* ─── Summary Cards ─── */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-4 mb-6">
        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-codex-text-primary">
            {stats.total_rules || 0}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            总规则数
          </div>
        </div>

        <div className="card p-5 text-center border-l-2 border-l-red-500">
          <div className="font-mono text-3xl font-bold text-red-400">
            {stats.high_risk || 0}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            高风险
          </div>
        </div>

        <div className="card p-5 text-center border-l-2 border-l-amber-500">
          <div className="font-mono text-3xl font-bold text-amber-400">
            {stats.medium_risk || 0}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            中风险
          </div>
        </div>

        <div className="card p-5 text-center border-l-2 border-l-emerald-500">
          <div className="font-mono text-3xl font-bold text-emerald-400">
            {stats.low_risk || 0}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            低风险
          </div>
        </div>

        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-codex-text-primary">
            {stats.conflicts || 0}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            需复核
          </div>
        </div>

        <div className="card p-5 text-center">
          <div className="font-mono text-3xl font-bold text-codex-text-primary">
            {stats.tokens_used
              ? (stats.tokens_used / 1000).toFixed(0) + 'K'
              : '-'}
          </div>
          <div className="text-xs text-codex-text-muted uppercase tracking-wider mt-1">
            总Token
          </div>
        </div>
      </div>

      {/* ─── Filters Bar ─── */}
      <div className="card p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">风险级别</label>
            <select
              value={filters.risk_level || ''}
              onChange={(e) =>
                handleFilterChange('risk_level', e.target.value || undefined)
              }
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">管道</label>
            <select
              value={filters.pipeline || ''}
              onChange={(e) =>
                handleFilterChange('pipeline', e.target.value || undefined)
              }
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
            <label className="block text-xs text-codex-text-muted mb-1">冲突标记</label>
            <select
              value={filters.conflict_flag || ''}
              onChange={(e) =>
                handleFilterChange('conflict_flag', e.target.value || undefined)
              }
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="conflict">冲突</option>
              <option value="variant">变体</option>
              <option value="consistent">一致</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">合同类型</label>
            <select
              value={filters.contract_type || ''}
              onChange={(e) =>
                handleFilterChange('contract_type', e.target.value || undefined)
              }
              className="select-field text-xs"
            >
              <option value="">全部</option>
              {[
                '采购',
                '销售',
                '服务',
                '保密',
                '技术',
                '许可',
                '租赁',
                '劳动',
                '通用商事',
              ].map((ct) => (
                <option key={ct} value={ct}>
                  {ct}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">来源文件</label>
            <select
              value={filters.source_file || ''}
              onChange={(e) =>
                handleFilterChange('source_file', e.target.value || undefined)
              }
              className="select-field text-xs"
            >
              <option value="">全部</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">
              置信度: {filters.confidence_min ?? 0} - {filters.confidence_max ?? 1}
            </label>
            <div className="flex gap-2">
              <input
                type="number"
                value={filters.confidence_min ?? ''}
                onChange={(e) =>
                  handleFilterChange(
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
              <span className="text-codex-text-muted text-xs self-center">-</span>
              <input
                type="number"
                value={filters.confidence_max ?? ''}
                onChange={(e) =>
                  handleFilterChange(
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

        {/* Active filter pills */}
        {activeFilters.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-codex-border">
            <span className="text-xs text-codex-text-muted">当前筛选:</span>
            {activeFilters.map((af) => (
              <span
                key={af.key}
                className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs bg-codex-bg-tertiary text-codex-text-secondary border border-codex-border"
              >
                {af.label}: {af.value}
                <button
                  type="button"
                  onClick={() => {
                    if (af.key === 'confidence') {
                      handleFilterChange('confidence_min', undefined)
                      handleFilterChange('confidence_max', undefined)
                    } else {
                      handleFilterChange(
                        af.key as keyof BatchRuleFilters,
                        undefined,
                      )
                    }
                  }}
                  className="text-codex-text-muted hover:text-codex-text-primary ml-0.5"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
            {activeFilters.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setFilters({
                    risk_level: '',
                    pipeline: '',
                    conflict_flag: '',
                    contract_type: '',
                    source_file: '',
                    confidence_min: undefined,
                    confidence_max: undefined,
                    page: 1,
                    page_size: 50,
                  })
                  setPage(1)
                }}
                className="text-xs text-codex-text-muted hover:text-codex-text-primary underline ml-2"
              >
                清除全部
              </button>
            )}
          </div>
        )}
      </div>

      {/* ─── Rule Table ─── */}
      <div className="card overflow-hidden mb-6">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-codex-border">
            <thead>
              <tr className="bg-codex-bg-secondary">
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  规则ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  风险
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  检查项
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider max-w-xs">
                  审查要求
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  管道
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  置信度
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  冲突
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-codex-text-muted uppercase tracking-wider">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-codex-border">
              {rules.length === 0 ? (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-10 text-center text-codex-text-muted"
                  >
                    暂无数据
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr
                    key={rule.rule_id}
                    className="hover:bg-codex-bg-tertiary cursor-pointer transition-colors"
                    onClick={() => setSelectedRule(rule)}
                  >
                    <td className="px-4 py-3 text-sm font-mono text-codex-text-muted whitespace-nowrap">
                      {rule.rule_id}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={rule.risk_level} />
                    </td>
                    <td className="px-4 py-3 text-sm text-codex-text-primary max-w-xs truncate">
                      {rule.check_item}
                    </td>
                    <td className="px-4 py-3 text-sm text-codex-text-secondary max-w-xs truncate">
                      {rule.requirement}
                    </td>
                    <td className="px-4 py-3">
                      <PipelineBadge pipeline={rule.pipeline} />
                    </td>
                    <td className="px-4 py-3">
                      <ConfidenceBar value={rule.confidence} />
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
                        className="text-accent hover:text-amber-300 text-sm font-medium transition-colors"
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
          <div className="flex items-center justify-between px-4 py-3 border-t border-codex-border">
            <div className="text-sm text-codex-text-muted">
              共 {total} 条，第 {page} / {totalPages} 页
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => {
                  const p = Math.max(1, page - 1)
                  setPage(p)
                  setFilters((prev) => ({ ...prev, page: p }))
                }}
                disabled={page <= 1}
                className="btn-secondary text-xs py-1 px-3"
              >
                上一页
              </button>
              <button
                type="button"
                onClick={() => {
                  const p = Math.min(totalPages, page + 1)
                  setPage(p)
                  setFilters((prev) => ({ ...prev, page: p }))
                }}
                disabled={page >= totalPages}
                className="btn-secondary text-xs py-1 px-3"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ─── Bottom Action Bar ─── */}
      <div className="sticky bottom-0 bg-codex-bg-secondary/90 backdrop-blur-sm border-t border-codex-border px-6 py-3 flex items-center justify-between rounded-card mt-6">
        <div className="flex items-center gap-2">
          <span className="text-xs text-codex-text-muted mr-2">导出:</span>
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
            冲突报告
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'change-set')}
            className="btn-secondary text-xs py-1.5 px-3"
          >
            变更集
          </button>
        </div>
        <button
          type="button"
          onClick={handleApply}
          disabled={applying}
          className="btn-primary text-sm shadow-glow"
        >
          {applying ? '合并中...' : '合并到主库'}
        </button>
      </div>

      {/* ─── Detail Drawer ─── */}
      {selectedRule && (
        <div className="fixed inset-0 z-50 flex justify-end">
          {/* Overlay */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setSelectedRule(null)}
          />

          {/* Drawer panel */}
          <div className="relative w-full sm:w-[520px] bg-codex-bg-secondary border-l border-codex-border shadow-2xl overflow-y-auto h-full animate-fade-in">
            {/* Drawer header */}
            <div className="sticky top-0 z-10 bg-codex-bg-secondary/95 backdrop-blur-sm border-b border-codex-border px-6 py-4 flex items-center justify-between">
              <h3 className="font-display text-lg text-codex-text-primary">
                规则详情
              </h3>
              <button
                type="button"
                onClick={() => setSelectedRule(null)}
                className="text-codex-text-muted hover:text-codex-text-primary transition-colors p-1 rounded-btn hover:bg-codex-bg-tertiary"
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

            {/* Drawer body */}
            <div className="px-6 py-4 space-y-4">
              {/* Basic info grid */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">规则ID</div>
                  <div className="text-sm font-mono text-codex-text-primary">
                    {selectedRule.rule_id}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">风险级别</div>
                  <RiskBadge level={selectedRule.risk_level} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">管道</div>
                  <PipelineBadge pipeline={selectedRule.pipeline} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">冲突状态</div>
                  <ConflictBadge flag={selectedRule.conflict_flag} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">置信度</div>
                  <ConfidenceBar value={selectedRule.confidence} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">来源文件</div>
                  <div className="text-sm text-codex-text-primary truncate">
                    {selectedRule.source_file || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">合同类型</div>
                  <div className="text-sm text-codex-text-primary">
                    {selectedRule.contract_types?.join(', ') || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">主题</div>
                  <div className="text-sm text-codex-text-primary">
                    {selectedRule.theme_key || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">规则类型</div>
                  <div className="text-sm text-codex-text-primary">
                    {selectedRule.rule_type || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-0.5">版本</div>
                  <div className="text-sm text-codex-text-primary">
                    {selectedRule.version || '-'}
                  </div>
                </div>
              </div>

              {/* Keywords */}
              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-1.5">关键词</div>
                <div className="flex flex-wrap gap-1.5">
                  {selectedRule.keywords?.length > 0
                    ? selectedRule.keywords.map((kw, i) => (
                        <span
                          key={i}
                          className="inline-flex px-2 py-0.5 rounded text-xs bg-accent-soft text-accent font-medium"
                        >
                          {kw}
                        </span>
                      ))
                    : <span className="text-sm text-codex-text-muted">-</span>}
                </div>
              </div>

              {/* Check item */}
              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-1.5">检查项</div>
                <div className="text-sm text-codex-text-primary whitespace-pre-wrap leading-relaxed">
                  {selectedRule.check_item}
                </div>
              </div>

              {/* Requirement */}
              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-1.5">审查要求</div>
                <div className="text-sm text-codex-text-primary whitespace-pre-wrap leading-relaxed">
                  {selectedRule.requirement}
                </div>
              </div>

              {/* Notes */}
              {selectedRule.notes && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1.5">备注</div>
                  <div className="text-sm text-codex-text-secondary whitespace-pre-wrap leading-relaxed">
                    {selectedRule.notes}
                  </div>
                </div>
              )}

              {/* Source excerpt */}
              {selectedRule.source_excerpt && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1.5">原文摘录</div>
                  <div className="bg-codex-bg-tertiary rounded-input p-4 font-mono text-sm text-codex-text-primary leading-relaxed border border-codex-border">
                    <HighlightedExcerpt
                      text={selectedRule.source_excerpt}
                      keywords={selectedRule.keywords}
                    />
                  </div>
                </div>
              )}

              {/* Ladder info */}
              {!!selectedRule.ladder_info && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1.5">
                    阶梯信息 (P4)
                  </div>
                  <LadderDisplay ladderInfo={selectedRule.ladder_info} />
                </div>
              )}

              {/* Cited cases */}
              {selectedRule.cited_cases && selectedRule.cited_cases.length > 0 && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1.5">
                    引用案例 (P5)
                  </div>
                  <CitedCasesDisplay cases={selectedRule.cited_cases} />
                </div>
              )}

              {/* Variants */}
              {selectedRule.variants && selectedRule.variants.length > 0 && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1.5">变体版本</div>
                  <pre className="text-xs text-codex-text-secondary bg-codex-bg-tertiary p-3 rounded-input overflow-x-auto border border-codex-border">
                    {JSON.stringify(selectedRule.variants, null, 2)}
                  </pre>
                </div>
              )}

              {/* Confidence details */}
              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-2">置信度明细</div>
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-codex-text-secondary">自身置信度</span>
                    <ConfidenceBar value={selectedRule.confidence_self} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-codex-text-secondary">一致性</span>
                    <ConfidenceBar value={selectedRule.confidence_consistency} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-codex-text-secondary">结构化</span>
                    <ConfidenceBar value={selectedRule.confidence_struct} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-codex-text-secondary">冲突检测</span>
                    <ConfidenceBar value={selectedRule.confidence_conflict} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
