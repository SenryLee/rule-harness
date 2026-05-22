import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchBatches, deleteBatch, downloadExport } from '../api'
import type { Batch, ExportKind } from '../api'

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { className: string; label: string }> = {
    success: { className: 'badge-success', label: '成功' },
    completed: { className: 'badge-success', label: '已完成' },
    partial: { className: 'badge-warning', label: '部分完成' },
    failed: { className: 'badge-danger', label: '失败' },
    running: { className: 'badge-info animate-pulse', label: '运行中' },
    pending: { className: 'badge-info', label: '等待中' },
  }
  const config = map[status] || { className: 'badge-info', label: status }
  return <span className={config.className}>{config.label}</span>
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '-'
  }
}

export default function BatchesPage() {
  const navigate = useNavigate()
  const [batches, setBatches] = useState<Batch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openMenu, setOpenMenu] = useState<string | null>(null)

  const loadBatches = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchBatches()
      setBatches(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBatches()
  }, [loadBatches])

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm('确认删除该批次？此操作不可撤销。')) return
      try {
        await deleteBatch(id)
        setBatches((prev) => prev.filter((b) => b.batch_id !== id))
      } catch (err) {
        alert(err instanceof Error ? err.message : '删除失败')
      }
    },
    []
  )

  const handleExport = useCallback((id: string, kind: ExportKind) => {
    downloadExport(id, kind)
    setOpenMenu(null)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
        <span className="ml-3 text-codex-text-muted">加载批次列表...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded-lg text-red-400 text-sm">
          {error}
        </div>
        <button type="button" onClick={loadBatches} className="btn-secondary">
          重试
        </button>
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-2xl text-codex-text-primary border-b-2 border-accent pb-2 inline-block">
          历史任务
        </h1>
        <button type="button" onClick={loadBatches} className="btn-secondary text-sm">
          刷新
        </button>
      </div>

      {batches.length === 0 ? (
        <div className="card p-10 text-center max-w-lg mx-auto mt-16">
          <div className="flex justify-center mb-4">
            <svg
              className="w-16 h-16 text-codex-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z"
              />
            </svg>
          </div>
          <h3 className="text-codex-text-primary text-lg font-body mb-2">暂无历史任务</h3>
          <p className="text-codex-text-muted text-sm mb-6">
            点击上方「新建任务」开始第一次规则抽取
          </p>
          <button
            type="button"
            onClick={() => navigate('/run')}
            className="btn-primary"
          >
            新建任务
          </button>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-codex-border">
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    批次ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    开始时间
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    结束时间
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    状态
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    规则统计
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    Token消耗
                  </th>
                  <th className="px-4 py-3 text-left text-xs text-codex-text-muted uppercase tracking-wider font-medium">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => {
                  const s = batch.stats || {}
                  const statsSummary = [
                    s.new_rules != null && `新${s.new_rules}`,
                    s.modified_rules != null && `改${s.modified_rules}`,
                    s.conflicts != null && `冲突${s.conflicts}`,
                  ]
                    .filter(Boolean)
                    .join(' / ')

                  return (
                    <tr
                      key={batch.batch_id}
                      className="border-b border-codex-border hover:bg-codex-bg-tertiary transition-colors"
                    >
                      <td className="px-4 py-3 text-sm font-mono text-codex-text-secondary max-w-[180px] truncate">
                        {batch.batch_id}
                      </td>
                      <td className="px-4 py-3 text-sm text-codex-text-secondary whitespace-nowrap">
                        {formatDate(batch.started_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-codex-text-secondary whitespace-nowrap">
                        {formatDate(batch.finished_at)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={batch.status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-codex-text-secondary">
                        <div>{s.total_rules != null ? `${s.total_rules} 条` : '-'}</div>
                        {statsSummary && (
                          <div className="font-mono text-xs mt-1 space-x-1">
                            {s.new_rules != null && (
                              <span className="text-emerald-400">新:{s.new_rules}</span>
                            )}
                            {s.modified_rules != null && (
                              <span className="text-amber-400">改:{s.modified_rules}</span>
                            )}
                            {s.conflicts != null && (
                              <span className="text-red-400">冲:{s.conflicts}</span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-sm text-accent">
                          {s.tokens_used != null
                            ? s.tokens_used.toLocaleString()
                            : '-'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2 relative">
                          <button
                            type="button"
                            onClick={() => {
                              navigate(`/report/${batch.batch_id}`)
                            }}
                            className="text-accent hover:text-amber-300 text-sm font-medium transition-colors"
                          >
                            查看报告
                          </button>
                          <div className="relative">
                            <button
                              type="button"
                              onClick={() =>
                                setOpenMenu(
                                  openMenu === batch.batch_id ? null : batch.batch_id
                                )
                              }
                              className="btn-ghost text-sm"
                            >
                              导出
                            </button>
                            {openMenu === batch.batch_id && (
                              <div className="absolute right-0 mt-1 w-40 bg-codex-bg-secondary rounded-card shadow-glow-lg border border-codex-border py-1 z-10 animate-fade-in">
                                {(
                                  [
                                    ['main-csv', '主CSV'],
                                    ['metadata-csv', '元数据CSV'],
                                    ['conflict-report', '冲突报告'],
                                    ['change-set', '变更集CSV'],
                                  ] as const
                                ).map(([kind, label]) => (
                                  <button
                                    key={kind}
                                    type="button"
                                    onClick={() => handleExport(batch.batch_id, kind)}
                                    className="block w-full text-left px-4 py-2 text-sm text-codex-text-secondary hover:bg-codex-bg-tertiary transition-colors"
                                  >
                                    {label}
                                  </button>
                                ))}
                                <div className="border-t border-codex-border">
                                  <button
                                    type="button"
                                    onClick={() => {
                                      handleDelete(batch.batch_id)
                                      setOpenMenu(null)
                                    }}
                                    className="block w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-900/20 transition-colors"
                                  >
                                    删除
                                  </button>
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
