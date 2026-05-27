import { useCallback, useEffect, useMemo, useState } from 'react';
import { deleteBatch, fetchBatches } from '../api';
import type { Batch } from '../api';

interface TaskPanelProps {
  selectedBatchId: string | null;
  pendingNewTask: boolean;
  onSelectBatch: (batch: Batch | null) => void;
  refreshKey: number;
}

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '-';
  }
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { className: string; label: string }> = {
    completed: { className: 'badge-success', label: '已完成' },
    success: { className: 'badge-success', label: '已完成' },
    merged: { className: 'badge-success', label: '已入库' },
    partial: { className: 'badge-warning', label: '部分完成' },
    failed: { className: 'badge-danger', label: '失败' },
    running: { className: 'badge-info', label: '运行中' },
    pending: { className: 'badge-gray', label: '等待中' },
  };
  const config = map[status] || { className: 'badge-gray', label: status };
  return <span className={config.className}>{config.label}</span>;
}

export default function TaskPanel({
  selectedBatchId,
  pendingNewTask,
  onSelectBatch,
  refreshKey,
}: TaskPanelProps) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchBatches();
      setBatches(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches, refreshKey]);

  const totalRunning = useMemo(
    () => batches.filter((batch) => batch.status === 'running' || batch.status === 'pending').length,
    [batches],
  );

  const handleDelete = useCallback(
    async (batch: Batch) => {
      if (!confirm('确认删除该任务？此操作不可撤销。')) return;
      try {
        await deleteBatch(batch.batch_id);
        if (selectedBatchId === batch.batch_id) {
          onSelectBatch(null);
        }
        setBatches((prev) => prev.filter((item) => item.batch_id !== batch.batch_id));
      } catch (err) {
        alert(err instanceof Error ? err.message : '删除失败');
      }
    },
    [onSelectBatch, selectedBatchId],
  );

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-air-border flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">任务列表</h2>
          <div className="text-[11px] text-gray-400 mt-0.5">
            {batches.length} 个任务{totalRunning > 0 ? ` · ${totalRunning} 个运行中` : ''}
          </div>
        </div>
        <button
          type="button"
          onClick={loadBatches}
          className="btn-ghost text-xs py-1 px-2"
          title="刷新任务"
        >
          刷新
        </button>
      </div>

      {pendingNewTask && (
        <button
          type="button"
          onClick={() => onSelectBatch(null)}
          className="w-full text-left px-4 py-3 bg-primary-soft border-l-[3px] border-l-primary border-b border-air-border"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="badge-info">新任务</span>
            <span className="text-[10px] text-primary">未启动</span>
          </div>
          <div className="text-xs text-gray-600">上传文件并启动审查</div>
        </button>
      )}

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary/20 border-t-primary" />
            <span className="ml-2 text-xs text-gray-400">加载中...</span>
          </div>
        ) : error ? (
          <div className="px-4 py-4">
            <div className="p-3 bg-red-50 border border-red-200 rounded-card text-red-600 text-xs">
              {error}
            </div>
            <button type="button" onClick={loadBatches} className="btn-secondary text-xs mt-2 w-full">
              重试
            </button>
          </div>
        ) : batches.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <div className="text-sm font-medium text-gray-500">暂无历史任务</div>
            <p className="text-xs text-gray-400 mt-1">点击顶部“新建任务”开始。</p>
          </div>
        ) : (
          <div className="divide-y divide-air-border">
            {batches.map((batch) => {
              const isSelected = selectedBatchId === batch.batch_id;
              const stats = batch.stats || batch.summary || {};
              return (
                <button
                  key={batch.batch_id}
                  type="button"
                  onClick={() => onSelectBatch(isSelected ? null : batch)}
                  className={`w-full text-left px-4 py-3 transition-colors hover:bg-air-hover ${
                    isSelected
                      ? 'bg-primary-soft border-l-[3px] border-l-primary'
                      : 'border-l-[3px] border-l-transparent'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <StatusBadge status={batch.status} />
                    <span className="text-[10px] text-gray-400">
                      {formatDate(batch.started_at)}
                    </span>
                  </div>
                  <div className="text-xs font-mono text-gray-500 truncate mb-1">
                    {batch.batch_id}
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-gray-400">
                    {batch.total_files != null && <span>{batch.total_files} 个文件</span>}
                    {stats.total_rules != null && <span>{stats.total_rules} 条规则</span>}
                    {stats.high_risk != null && stats.high_risk > 0 && (
                      <span className="text-red-500">{stats.high_risk} 高风险</span>
                    )}
                  </div>
                  {isSelected && (
                    <div className="mt-2 flex justify-end border-t border-air-border pt-2">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDelete(batch);
                        }}
                        className="btn-ghost text-[10px] py-1 px-2 text-red-500 hover:text-red-600"
                      >
                        删除
                      </button>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
