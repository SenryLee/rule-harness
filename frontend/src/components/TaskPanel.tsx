import { useCallback, useEffect, useMemo, useState } from 'react';
import { deleteBatch, fetchBatches } from '../api';
import type { Batch } from '../api';
import { Icon } from './Ui';

interface TaskPanelProps {
  selectedBatchId: string | null;
  pendingNewTask: boolean;
  onSelectBatch: (batch: Batch | null) => void;
  onNewTask: () => void;
  onOpenConfig: () => void;
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
  onNewTask,
  onOpenConfig,
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
    <div className="flex h-full flex-col border-r border-[var(--border)] bg-[var(--bg-surface)]">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-[var(--border)] px-5 py-4">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-[var(--primary)] to-[#3B82F6] text-white shadow-sm">
          <Icon name="book" size={18} strokeWidth={2} />
        </div>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-bold tracking-normal text-[var(--text-primary)]">规则梳理</div>
          <div className="text-[11px] font-medium text-[var(--text-muted)]">Harness v2.0</div>
        </div>
      </div>

      <nav className="flex-shrink-0 px-3 pb-2 pt-3">
        <button type="button" className="sidebar-nav-item active w-full">
          <span className="sidebar-nav-indicator" />
          <Icon name="upload" size={18} />
          <span className="flex-1">任务工作台</span>
          <span className="kbd">1</span>
        </button>
        <button type="button" onClick={onOpenConfig} className="sidebar-nav-item w-full">
          <Icon name="settings" size={18} />
          <span className="flex-1">系统设置</span>
          <span className="kbd">2</span>
        </button>
      </nav>

      <div className="mx-5 h-px flex-shrink-0 bg-[var(--border)]" />

      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <div>
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--text-muted)]">历史任务</h2>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">
            {batches.length} 个任务{totalRunning > 0 ? ` · ${totalRunning} 个运行中` : ''}
          </div>
        </div>
        <button type="button" onClick={onNewTask} className="icon-button primary" title="新建任务">
          <Icon name="plus" size={15} strokeWidth={2.2} />
        </button>
      </div>

      {pendingNewTask && (
        <button
          type="button"
          onClick={() => onSelectBatch(null)}
          className="mx-3 mb-2 rounded-md border border-[var(--border-accent)] bg-[var(--primary-soft)] px-3 py-3 text-left shadow-[var(--shadow-xs)]"
        >
          <div className="flex items-center justify-between mb-1">
            <span className="badge-info">新任务</span>
            <span className="text-[10px] font-medium text-[var(--primary)]">未启动</span>
          </div>
          <div className="text-xs text-[var(--text-secondary)]">上传文件并启动审查</div>
        </button>
      )}

      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary/20 border-t-primary" />
            <span className="ml-2 text-xs text-[var(--text-muted)]">加载中...</span>
          </div>
        ) : error ? (
          <div className="py-4">
            <div className="p-3 bg-red-50 border border-red-200 rounded-card text-red-600 text-xs">
              {error}
            </div>
            <button type="button" onClick={loadBatches} className="btn-secondary mt-2 w-full text-xs">
              <Icon name="refresh" size={14} />
              重试加载
            </button>
          </div>
        ) : batches.length === 0 ? (
          <div className="py-10 text-center">
            <div className="text-sm font-medium text-[var(--text-secondary)]">暂无历史任务</div>
            <p className="mt-1 text-xs text-[var(--text-muted)]">点击加号开始。</p>
          </div>
        ) : (
          <div className="space-y-1">
            {batches.map((batch) => {
              const isSelected = selectedBatchId === batch.batch_id;
              const stats = batch.stats || batch.summary || {};
              return (
                <button
                  key={batch.batch_id}
                  type="button"
                  onClick={() => onSelectBatch(isSelected ? null : batch)}
                  className={`task-item ${
                    isSelected
                      ? 'selected'
                      : ''
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <StatusBadge status={batch.status} />
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {formatDate(batch.started_at)}
                    </span>
                  </div>
                  <div className="mb-1 truncate font-mono text-xs text-[var(--text-muted)]">
                    {batch.batch_id}
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
                    {batch.total_files != null && <span>{batch.total_files} 个文件</span>}
                    {stats.total_rules != null && <span>{stats.total_rules} 条规则</span>}
                    {stats.high_risk != null && stats.high_risk > 0 && (
                      <span className="text-red-500">{stats.high_risk} 高风险</span>
                    )}
                  </div>
                  {isSelected && (
                    <div className="mt-2 flex justify-end border-t border-[var(--border)] pt-2">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDelete(batch);
                        }}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-red-500 transition-colors hover:bg-red-50 hover:text-red-600"
                      >
                        <Icon name="trash" size={12} />
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

      <div className="flex flex-shrink-0 items-center justify-between border-t border-[var(--border)] px-5 py-3 text-[11px] text-[var(--text-muted)]">
        <span>命令面板</span>
        <span className="kbd">⌘K</span>
      </div>
    </div>
  );
}
