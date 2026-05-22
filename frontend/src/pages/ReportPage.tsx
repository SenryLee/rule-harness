import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  fetchBatch,
  fetchBatchRules,
  downloadExport,
  applyMerge,
} from '../api'
import type { Batch, RuleItem, BatchRuleFilters } from '../api'

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    high: 'badge-red',
    medium: 'badge-yellow',
    low: 'badge-green',
  }
  const label: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
  }
  return <span className={map[level] || 'badge-gray'}>{label[level] || level}</span>
}

function PipelineBadge({ pipeline }: { pipeline?: string }) {
  if (!pipeline) return <span className="badge-gray">-</span>
  const map: Record<string, string> = {
    P1: 'badge-blue',
    P5: 'badge-purple',
    direct: 'badge-teal',
  }
  return <span className={map[pipeline] || 'badge-gray'}>{pipeline}</span>
}

function ConflictBadge({ flag }: { flag?: string }) {
  if (!flag) return null
  const map: Record<string, string> = {
    conflict: 'badge-red',
    variant: 'badge-yellow',
    consistent: 'badge-green',
  }
  const label: Record<string, string> = {
    conflict: '冲突',
    variant: '变体',
    consistent: '一致',
  }
  return <span className={map[flag] || 'badge-gray'}>{label[flag] || flag}</span>
}

function ConfidenceBar({ value }: { value?: number }) {
  if (value === undefined || value === null) return <span className="text-gray-400 text-sm">-</span>
  const pct = Math.round(value * 100)
  const color =
    pct >= 80 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 bg-gray-200 rounded-full h-2">
        <div
          className={`${color} h-2 rounded-full transition-all`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-gray-600 w-8">{pct}%</span>
    </div>
  )
}

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
    []
  )

  const handleApply = useCallback(async () => {
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

  const totalPages = Math.ceil(total / pageSize)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
        <span className="ml-3 text-gray-500">加载报告数据...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 bg-red-50 border border-red-200 rounded-lg text-red-700">
        加载失败: {error}
      </div>
    )
  }

  if (!batch) {
    return <div className="text-gray-500">批次不存在</div>
  }

  const stats = batch.stats || {}

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-900">批次报告</h2>
          <div className="text-sm text-gray-500 font-mono mt-1">{batchId}</div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'main-csv')}
            className="btn-secondary text-sm"
          >
            主CSV
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'metadata-csv')}
            className="btn-secondary text-sm"
          >
            元数据CSV
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'conflict-report')}
            className="btn-secondary text-sm"
          >
            冲突报告
          </button>
          <button
            type="button"
            onClick={() => downloadExport(batchId!, 'change-set')}
            className="btn-secondary text-sm"
          >
            变更集
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={applying}
            className="btn-primary text-sm"
          >
            {applying ? '合并中...' : '合并到主库'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 md:grid-cols-6 gap-4 mb-6">
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-gray-800">{stats.total_rules || 0}</div>
          <div className="text-xs text-gray-500 mt-1">规则总数</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-red-600">{stats.high_risk || 0}</div>
          <div className="text-xs text-gray-500 mt-1">高风险</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-yellow-600">{stats.medium_risk || 0}</div>
          <div className="text-xs text-gray-500 mt-1">中风险</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-green-600">{stats.low_risk || 0}</div>
          <div className="text-xs text-gray-500 mt-1">低风险</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-orange-600">{stats.conflicts || 0}</div>
          <div className="text-xs text-gray-500 mt-1">冲突数</div>
        </div>
        <div className="card p-4 text-center">
          <div className="text-2xl font-bold text-blue-600">
            {stats.tokens_used ? (stats.tokens_used / 1000).toFixed(0) + 'K' : '-'}
          </div>
          <div className="text-xs text-gray-500 mt-1">Token消耗</div>
        </div>
      </div>

      <div className="card p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">风险级别</label>
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
            <label className="block text-xs text-gray-500 mb-1">管道</label>
            <select
              value={filters.pipeline || ''}
              onChange={(e) => handleFilterChange('pipeline', e.target.value || undefined)}
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
            <label className="block text-xs text-gray-500 mb-1">冲突标记</label>
            <select
              value={filters.conflict_flag || ''}
              onChange={(e) => handleFilterChange('conflict_flag', e.target.value || undefined)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
              <option value="conflict">冲突</option>
              <option value="variant">变体</option>
              <option value="consistent">一致</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">合同类型</label>
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
            <label className="block text-xs text-gray-500 mb-1">来源文件</label>
            <select
              value={filters.source_file || ''}
              onChange={(e) => handleFilterChange('source_file', e.target.value || undefined)}
              className="select-field text-xs"
            >
              <option value="">全部</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              置信度: {filters.confidence_min ?? 0} - {filters.confidence_max ?? 1}
            </label>
            <div className="flex gap-2">
              <input
                type="number"
                value={filters.confidence_min ?? ''}
                onChange={(e) =>
                  handleFilterChange(
                    'confidence_min',
                    e.target.value ? Number(e.target.value) : undefined
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
                value={filters.confidence_max ?? ''}
                onChange={(e) =>
                  handleFilterChange(
                    'confidence_max',
                    e.target.value ? Number(e.target.value) : undefined
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
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  规则ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  风险
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  检查项
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase max-w-xs">
                  审查要求
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  管道
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  置信度
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  冲突
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-gray-400">
                    暂无数据
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr key={rule.rule_id} className="hover:bg-gray-50 cursor-pointer">
                    <td className="px-4 py-3 text-sm font-mono text-gray-600 whitespace-nowrap">
                      {rule.rule_id}
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge level={rule.risk_level} />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-800 max-w-xs truncate">
                      {rule.check_item}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">
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
                        onClick={() => setSelectedRule(rule)}
                        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
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
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200">
            <div className="text-sm text-gray-500">
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

      {selectedRule && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div
            className="absolute inset-0 bg-black bg-opacity-30"
            onClick={() => setSelectedRule(null)}
          />
          <div className="relative w-full max-w-2xl bg-white shadow-xl overflow-y-auto h-full">
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">规则详情</h3>
              <button
                type="button"
                onClick={() => setSelectedRule(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            <div className="px-6 py-4 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-gray-500">规则ID</div>
                  <div className="text-sm font-mono text-gray-800">{selectedRule.rule_id}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">风险级别</div>
                  <RiskBadge level={selectedRule.risk_level} />
                </div>
                <div>
                  <div className="text-xs text-gray-500">管道</div>
                  <PipelineBadge pipeline={selectedRule.pipeline} />
                </div>
                <div>
                  <div className="text-xs text-gray-500">冲突状态</div>
                  <ConflictBadge flag={selectedRule.conflict_flag} />
                </div>
                <div>
                  <div className="text-xs text-gray-500">置信度</div>
                  <ConfidenceBar value={selectedRule.confidence} />
                </div>
                <div>
                  <div className="text-xs text-gray-500">来源文件</div>
                  <div className="text-sm text-gray-800 truncate">
                    {selectedRule.source_file || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">合同类型</div>
                  <div className="text-sm text-gray-800">
                    {selectedRule.contract_types?.join(', ') || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">主题</div>
                  <div className="text-sm text-gray-800">
                    {selectedRule.theme_key || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">规则类型</div>
                  <div className="text-sm text-gray-800">
                    {selectedRule.rule_type || '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">版本</div>
                  <div className="text-sm text-gray-800">{selectedRule.version || '-'}</div>
                </div>
              </div>

              <div className="pt-4 border-t border-gray-200">
                <div className="text-xs text-gray-500 mb-1">关键词</div>
                <div className="flex flex-wrap gap-1">
                  {selectedRule.keywords?.length > 0
                    ? selectedRule.keywords.map((kw, i) => (
                        <span
                          key={i}
                          className="inline-flex px-2 py-0.5 rounded text-xs bg-blue-50 text-blue-700"
                        >
                          {kw}
                        </span>
                      ))
                    : '-'}
                </div>
              </div>

              <div className="pt-4 border-t border-gray-200">
                <div className="text-xs text-gray-500 mb-1">检查项</div>
                <div className="text-sm text-gray-800 whitespace-pre-wrap">
                  {selectedRule.check_item}
                </div>
              </div>

              <div className="pt-4 border-t border-gray-200">
                <div className="text-xs text-gray-500 mb-1">审查要求</div>
                <div className="text-sm text-gray-800 whitespace-pre-wrap">
                  {selectedRule.requirement}
                </div>
              </div>

              {selectedRule.notes && (
                <div className="pt-4 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">备注</div>
                  <div className="text-sm text-gray-800 whitespace-pre-wrap">
                    {selectedRule.notes}
                  </div>
                </div>
              )}

              {selectedRule.source_excerpt && (
                <div className="pt-4 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">原文摘录</div>
                  <div className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 p-3 rounded-lg border border-gray-200">
                    {selectedRule.source_excerpt}
                  </div>
                </div>
              )}

              {!!selectedRule.ladder_info && (
                <div className="pt-4 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">阶梯信息 (P4)</div>
                  <pre className="text-xs text-gray-700 bg-gray-50 p-3 rounded-lg overflow-x-auto">
                    {JSON.stringify(selectedRule.ladder_info, null, 2)}
                  </pre>
                </div>
              )}

              {selectedRule.cited_cases && selectedRule.cited_cases.length > 0 && (
                <div className="pt-4 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">引用案例 (P5)</div>
                  <pre className="text-xs text-gray-700 bg-gray-50 p-3 rounded-lg overflow-x-auto">
                    {JSON.stringify(selectedRule.cited_cases, null, 2)}
                  </pre>
                </div>
              )}

              {selectedRule.variants && selectedRule.variants.length > 0 && (
                <div className="pt-4 border-t border-gray-200">
                  <div className="text-xs text-gray-500 mb-1">变体版本</div>
                  <pre className="text-xs text-gray-700 bg-gray-50 p-3 rounded-lg overflow-x-auto">
                    {JSON.stringify(selectedRule.variants, null, 2)}
                  </pre>
                </div>
              )}

              <div className="pt-4 border-t border-gray-200">
                <div className="text-xs text-gray-500 mb-2">置信度明细</div>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-600">自身置信度</span>
                    <ConfidenceBar value={selectedRule.confidence_self} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-600">一致性</span>
                    <ConfidenceBar value={selectedRule.confidence_consistency} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-600">结构化</span>
                    <ConfidenceBar value={selectedRule.confidence_struct} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-600">冲突检测</span>
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
