import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Clock, Pencil, Plus, X } from 'lucide-react';
import { deleteBatch, fetchBatches, patchBatch } from '../api';
import type { Batch } from '../api';

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    running: '进行中',
    stopping: '停止中',
    cancelled: '已停止',
    success: '完成',
    partial: '部分完成',
    merged: '已入库',
    failed: '失败',
  };
  return map[status] || status;
}

function statusBadgeClass(status: string): string {
  if (status === 'success' || status === 'merged') return 'badge-success';
  if (status === 'running') return 'badge-info';
  if (status === 'partial' || status === 'stopping' || status === 'cancelled') return 'badge-warning';
  return 'badge-danger';
}

export default function TaskList() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  const load = () => {
    setLoading(true);
    fetchBatches()
      .then(setBatches)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (id: string) => {
    try {
      await deleteBatch(id);
      load();
    } catch {
      // ignore
    }
  };

  const startRename = (batch: Batch) => {
    setEditingId(batch.batch_id);
    setEditName(batch.name || batch.batch_id);
  };

  const commitRename = async () => {
    if (!editingId) return;
    const name = editName.trim();
    if (name) {
      try {
        await patchBatch(editingId, { name });
        setBatches((prev) =>
          prev.map((b) => (b.batch_id === editingId ? { ...b, name } : b)),
        );
      } catch {
        // ignore
      }
    }
    setEditingId(null);
  };

  return (
    <div className="animate-page-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">任务中心</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">所有规则抽取任务和批次历史</p>
        </div>
        <Link to="/tasks/new" className="btn-primary">
          <Plus size={16} />
          新建任务
        </Link>
      </div>

      {loading ? (
        <div className="card px-6 py-12 text-center text-[var(--text-muted)]">加载中...</div>
      ) : batches.length === 0 ? (
        <div className="card px-6 py-16 text-center">
          <Clock size={32} className="mx-auto text-[var(--text-muted)] mb-3" />
          <p className="text-[var(--text-muted)]">暂无任务</p>
          <Link to="/tasks/new" className="mt-3 inline-block text-sm text-[var(--color-accent)]">
            创建第一个任务 →
          </Link>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-light)] text-left text-xs font-medium text-[var(--text-muted)]">
                <th className="px-5 py-3">任务名称</th>
                <th className="px-5 py-3">状态</th>
                <th className="px-5 py-3">文件数</th>
                <th className="px-5 py-3">规则数</th>
                <th className="px-5 py-3">时间</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.batch_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="max-w-[320px] px-5 py-4">
                    {editingId === batch.batch_id ? (
                      <span className="flex items-center gap-1.5">
                        <input
                          autoFocus
                          className="input-field py-1 text-sm"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitRename();
                            if (e.key === 'Escape') setEditingId(null);
                          }}
                        />
                        <button onClick={commitRename} className="text-[var(--color-green)]"><Check size={15} /></button>
                        <button onClick={() => setEditingId(null)} className="text-[var(--text-muted)]"><X size={15} /></button>
                      </span>
                    ) : (
                      <span className="group flex items-center gap-1.5">
                        <Link
                          to={`/tasks/${batch.batch_id}`}
                          className="truncate font-medium text-[var(--text-primary)] hover:text-[var(--color-accent)] hover:underline"
                          title={batch.name || batch.batch_id}
                        >
                          {batch.name || batch.batch_id}
                        </Link>
                        <button
                          onClick={() => startRename(batch)}
                          className="text-[var(--text-muted)] opacity-0 transition-opacity hover:text-[var(--color-accent)] group-hover:opacity-100"
                          title="重命名"
                        >
                          <Pencil size={13} />
                        </button>
                      </span>
                    )}
                    <span className="mt-0.5 block font-mono text-[10px] text-[var(--text-muted)]">
                      {batch.batch_id}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    <span className={statusBadgeClass(batch.status)}>{statusLabel(batch.status)}</span>
                  </td>
                  <td className="px-5 py-4">{batch.total_files ?? 0}</td>
                  <td className="px-5 py-4">{batch.stats?.total_rules ?? batch.summary?.total_rules ?? '—'}</td>
                  <td className="px-5 py-4 text-xs text-[var(--text-muted)]">{batch.started_at?.slice(0, 16).replace('T', ' ')}</td>
                  <td className="px-5 py-4 text-right">
                    {batch.status !== 'running' && (
                      <button
                        onClick={() => handleDelete(batch.batch_id)}
                        className="text-xs text-[var(--text-muted)] hover:text-[var(--color-red)]"
                      >
                        删除
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
