import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchBatches, deleteBatch, downloadExport } from '../api'
import type { Batch, ExportKind } from '../api'

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { className: string; label: string }> = {
    success: { className: 'badge-green', label: '成功' },
    completed: { className: 'badge-green', label: '已完成' },
    partial: { className: 'badge-yellow', label: '部分完成' },
    failed: { className: 'badge-red', label: '失败' },
    running: { className: 'badge-blue', label: '运行中' },
    pending: { className: 'badge-gray', label: '等待中' },
  }
  const config = map[status] || { className: 'badge-gray', label: status }
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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
        <span className="ml-3 text-gray-500">加载批次列表...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
        <button type="button" onClick={loadBatches} className="btn-secondary">
          重试
        </button>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900">历史任务</h1>
        <button type="button" onClick={loadBatches} className="btn-secondary text-sm">
          刷新
        </button>
      </div>

      {batches.length === 0 ? (
        <div className="card p-10 text-center text-gray-400">
          暂无批次数据
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    批次ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    开始时间
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    结束时间
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    状态
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    规则统计
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    Token消耗
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
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
                    <tr key={batch.batch_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm font-mono text-gray-600 max-w-[180px] truncate">
                        {batch.batch_id}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">
                        {formatDate(batch.started_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">
                        {formatDate(batch.finished_at)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={batch.status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        <div>{s.total_rules != null ? `${s.total_rules} 条` : '-'}</div>
                        {statsSummary && (
                          <div className="text-xs text-gray-400 mt-0.5">{statsSummary}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {s.tokens_used != null
                          ? s.tokens_used.toLocaleString()
                          : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2 relative">
                          <button
                            type="button"
                            onClick={() => {
                              if (batch.status === 'running' || batch.status === 'pending') {
                                navigate(`/report/${batch.batch_id}`)
                              } else {
                                navigate(`/report/${batch.batch_id}`)
                              }
                            }}
                            className="text-blue-600 hover:text-blue-800 text-sm font-medium"
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
                              className="text-gray-600 hover:text-gray-800 text-sm font-medium"
                            >
                              导出
                            </button>
                            {openMenu === batch.batch_id && (
                              <div className="absolute right-0 mt-1 w-40 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-10">
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
                                    className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                                  >
                                    {label}
                                  </button>
                                ))}
                                <div className="border-t border-gray-100">
                                  <button
                                    type="button"
                                    onClick={() => {
                                      handleDelete(batch.batch_id)
                                      setOpenMenu(null)
                                    }}
                                    className="block w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
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
