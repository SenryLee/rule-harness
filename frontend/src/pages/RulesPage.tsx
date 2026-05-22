import { useState, useEffect, useCallback } from 'react'
import {
  fetchRules,
  fetchThemes,
  fetchPendingThemes,
  approveThemes,
  toggleRuleEnabled,
} from '../api'
import type { RuleItem, RuleFilters, PendingThemeMapping } from '../api'

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
  return <span className={map[level] || 'badge-info'}>{label[level] || level}</span>
}

function ToggleSwitch({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onChange()
      }}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none ${
        enabled ? 'bg-accent' : 'bg-codex-bg-tertiary border border-codex-border'
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

function PipelineBadge({ pipeline }: { pipeline?: string }) {
  if (!pipeline) return <span className="text-codex-text-muted text-sm">-</span>
  return <span className="badge-accent">{pipeline}</span>
}

function RuleTypeBadge({ ruleType }: { ruleType?: string }) {
  if (!ruleType) return <span className="text-codex-text-muted text-sm">-</span>
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

function ConfidenceBar({ value }: { value?: number }) {
  if (value === undefined || value === null) return <span className="text-codex-text-muted text-sm">-</span>
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-codex-bg-tertiary rounded-full h-1.5">
        <div
          className="bg-accent h-1.5 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-codex-text-secondary w-7">{pct}%</span>
    </div>
  )
}

export default function RulesPage() {
  const [rules, setRules] = useState<RuleItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRule, setSelectedRule] = useState<RuleItem | null>(null)
  const [themes, setThemes] = useState<string[]>([])
  const [pendingThemes, setPendingThemes] = useState<PendingThemeMapping[]>([])
  const [showThemeManager, setShowThemeManager] = useState(false)

  const [filters, setFilters] = useState<RuleFilters>({
    risk_level: '',
    rule_type: '',
    theme_key: '',
    contract_type: '',
    enabled: undefined,
    search: '',
    page: 1,
    page_size: 50,
  })

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchRules({ ...filters, page, page_size: pageSize })
      .then((res) => {
        if (!cancelled) {
          setRules(res.rules)
          setTotal(res.total)
        }
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
  }, [filters, page, pageSize])

  useEffect(() => {
    fetchThemes()
      .then((res) => setThemes(res.keys))
      .catch(() => {})
    fetchPendingThemes()
      .then((res) => setPendingThemes(res.mappings || []))
      .catch(() => {})
  }, [])

  const handleFilterChange = useCallback(
    (key: keyof RuleFilters, value: string | boolean | undefined) => {
      setFilters((prev) => {
        const next = { ...prev, [key]: value ?? undefined }
        if (key !== 'page' && key !== 'page_size') {
          next.page = 1
        }
        return next
      })
      setPage(1)
    },
    []
  )

  const handleToggleEnabled = useCallback(async (rule: RuleItem) => {
    try {
      await toggleRuleEnabled(rule.rule_id, !rule.enabled)
      setRules((prev) =>
        prev.map((r) =>
          r.rule_id === rule.rule_id ? { ...r, enabled: !r.enabled } : r
        )
      )
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }, [])

  const handleApproveThemes = useCallback(async () => {
    const mappings = pendingThemes.map((m) => ({
      rule_id: m.rule_id,
      approved_theme: m.suggested_theme,
    }))
    try {
      await approveThemes(mappings)
      setPendingThemes([])
      alert('主题已批量确认')
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }, [pendingThemes])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-2xl text-codex-text-primary border-b-2 border-accent pb-2 inline-block">
          规则管理
        </h1>
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

      {showThemeManager && pendingThemes.length > 0 && (
        <div className="card p-4 mb-6 border-l-2 border-accent">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-body text-base font-semibold text-codex-text-primary">
              待审核主题
            </h3>
            <button type="button" onClick={handleApproveThemes} className="btn-primary text-sm">
              全部确认
            </button>
          </div>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {pendingThemes.map((m) => (
              <div
                key={m.rule_id}
                className="flex items-center justify-between py-2 px-3 bg-codex-bg-tertiary rounded-lg"
              >
                <div className="text-sm font-mono text-codex-text-secondary">{m.rule_id}</div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-codex-text-muted">{m.current_theme || '(空)'}</span>
                  <span className="text-codex-text-muted">→</span>
                  <span className="text-accent font-medium">{m.suggested_theme}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="card px-4 py-3 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">风险级别</label>
            <select
              value={filters.risk_level || ''}
              onChange={(e) => handleFilterChange('risk_level', e.target.value || undefined)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">规则类型</label>
            <select
              value={filters.rule_type || ''}
              onChange={(e) => handleFilterChange('rule_type', e.target.value || undefined)}
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
            <label className="block text-xs text-codex-text-muted mb-1">主题</label>
            <select
              value={filters.theme_key || ''}
              onChange={(e) => handleFilterChange('theme_key', e.target.value || undefined)}
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
            <label className="block text-xs text-codex-text-muted mb-1">合同类型</label>
            <select
              value={filters.contract_type || ''}
              onChange={(e) => handleFilterChange('contract_type', e.target.value || undefined)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              {['采购', '销售', '服务', '保密', '技术', '许可', '租赁', '劳动', '通用商事'].map(
                (ct) => (
                  <option key={ct} value={ct}>
                    {ct}
                  </option>
                )
              )}
            </select>
          </div>
          <div>
            <label className="block text-xs text-codex-text-muted mb-1">状态</label>
            <select
              value={
                filters.enabled === undefined ? '' : filters.enabled ? 'true' : 'false'
              }
              onChange={(e) => {
                const val = e.target.value
                handleFilterChange(
                  'enabled',
                  val === '' ? undefined : val === 'true'
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
            <label className="block text-xs text-codex-text-muted mb-1">搜索</label>
            <input
              type="text"
              value={filters.search || ''}
              onChange={(e) => handleFilterChange('search', e.target.value || undefined)}
              placeholder="检查项、要求..."
              className="input-field text-xs"
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
          <span className="ml-3 text-codex-text-muted">加载中...</span>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-codex-border">
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    规则ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    状态
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    风险
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    检查项
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium max-w-xs">
                    审查要求
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    管道
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    版本
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    主题
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {rules.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-codex-text-muted">
                      暂无规则数据
                    </td>
                  </tr>
                ) : (
                  rules.map((rule) => (
                    <tr
                      key={rule.rule_id}
                      className="border-b border-codex-border hover:bg-codex-bg-tertiary transition-colors"
                    >
                      <td className="px-4 py-3 text-sm font-mono text-codex-text-secondary whitespace-nowrap">
                        {rule.rule_id}
                      </td>
                      <td className="px-4 py-3">
                        <ToggleSwitch
                          enabled={rule.enabled}
                          onChange={() => handleToggleEnabled(rule)}
                        />
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
                      <td className="px-4 py-3 text-sm text-codex-text-secondary text-center">
                        v{rule.version || 1}
                      </td>
                      <td className="px-4 py-3 text-sm text-codex-text-muted max-w-[120px] truncate">
                        {rule.theme_key || '-'}
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
      )}

      {selectedRule && (
        <div className="fixed inset-0 z-50 flex justify-end animate-fade-in">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setSelectedRule(null)}
          />
          <div className="relative w-[520px] bg-codex-bg-secondary shadow-2xl overflow-y-auto h-full animate-slide-in-right">
            <div className="sticky top-0 bg-codex-bg-secondary border-b border-codex-border px-6 py-4 flex items-center justify-between z-10">
              <h3 className="font-body text-lg font-semibold text-codex-text-primary">规则详情</h3>
              <button
                type="button"
                onClick={() => setSelectedRule(null)}
                className="btn-ghost p-1 rounded-lg"
              >
                <svg className="w-5 h-5 text-codex-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            <div className="px-6 py-4 space-y-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">规则ID</div>
                  <div className="text-sm font-mono text-codex-text-primary">{selectedRule.rule_id}</div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">风险级别</div>
                  <RiskBadge level={selectedRule.risk_level} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">状态</div>
                  <div className={selectedRule.enabled ? 'text-emerald-400 text-sm' : 'text-codex-text-muted text-sm'}>
                    {selectedRule.enabled ? '已启用' : '已禁用'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">管道</div>
                  <PipelineBadge pipeline={selectedRule.pipeline} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">版本</div>
                  <div className="text-sm text-codex-text-primary">v{selectedRule.version || 1}</div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">主题</div>
                  <div className="text-sm text-codex-text-primary">{selectedRule.theme_key || '-'}</div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">规则类型</div>
                  <RuleTypeBadge ruleType={selectedRule.rule_type} />
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">合同类型</div>
                  <div className="text-sm text-codex-text-secondary">
                    {selectedRule.contract_types?.join(', ') || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">来源文件</div>
                  <div className="text-sm text-codex-text-secondary truncate">{selectedRule.source_file || '-'}</div>
                </div>
                <div>
                  <div className="text-xs text-codex-text-muted mb-1">批次</div>
                  <div className="text-sm font-mono text-codex-text-secondary truncate">{selectedRule.batch_id || '-'}</div>
                </div>
              </div>

              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-2">关键词</div>
                <div className="flex flex-wrap gap-1">
                  {selectedRule.keywords?.length > 0
                    ? selectedRule.keywords.map((kw, i) => (
                        <span
                          key={i}
                          className="inline-flex px-2 py-0.5 rounded text-xs bg-accent-soft text-accent"
                        >
                          {kw}
                        </span>
                      ))
                    : <span className="text-codex-text-muted text-sm">-</span>}
                </div>
              </div>

              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-1">检查项</div>
                <div className="text-sm text-codex-text-primary whitespace-pre-wrap">
                  {selectedRule.check_item}
                </div>
              </div>

              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-1">审查要求</div>
                <div className="text-sm text-codex-text-primary whitespace-pre-wrap">
                  {selectedRule.requirement}
                </div>
              </div>

              {selectedRule.notes && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1">备注</div>
                  <div className="text-sm text-codex-text-secondary whitespace-pre-wrap">
                    {selectedRule.notes}
                  </div>
                </div>
              )}

              {selectedRule.source_excerpt && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1">原文摘录</div>
                  <div className="text-sm text-codex-text-secondary whitespace-pre-wrap bg-codex-bg-tertiary p-3 rounded-lg border border-codex-border">
                    {selectedRule.source_excerpt}
                  </div>
                </div>
              )}

              {selectedRule.variants && selectedRule.variants.length > 0 && (
                <div className="pt-4 border-t border-codex-border">
                  <div className="text-xs text-codex-text-muted mb-1">变体版本</div>
                  <pre className="text-xs text-codex-text-secondary bg-codex-bg-tertiary p-3 rounded-lg overflow-x-auto border border-codex-border">
                    {JSON.stringify(selectedRule.variants, null, 2)}
                  </pre>
                </div>
              )}

              <div className="pt-4 border-t border-codex-border">
                <div className="text-xs text-codex-text-muted mb-2">置信度明细</div>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-codex-text-secondary">综合置信度</span>
                    <ConfidenceBar value={selectedRule.confidence} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-codex-text-secondary">自身置信度</span>
                    <ConfidenceBar value={selectedRule.confidence_self} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-codex-text-secondary">一致性</span>
                    <ConfidenceBar value={selectedRule.confidence_consistency} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-codex-text-secondary">结构化</span>
                    <ConfidenceBar value={selectedRule.confidence_struct} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-codex-text-secondary">冲突检测</span>
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
