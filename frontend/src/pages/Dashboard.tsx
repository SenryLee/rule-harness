import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, AlertTriangle, TrendingUp, Link2 } from 'lucide-react';
import { fetchBatches, fetchRules } from '../api';
import type { Batch } from '../api';

interface MetricCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  accent?: 'blue' | 'red' | 'green' | 'amber';
}

function MetricCard({ label, value, icon, accent = 'blue' }: MetricCardProps) {
  const accentMap = {
    blue: 'var(--color-blue-soft)',
    red: 'var(--color-red-soft)',
    green: 'var(--color-green-soft)',
    amber: 'var(--color-amber-soft)',
  };
  const colorMap = {
    blue: 'var(--color-blue)',
    red: 'var(--color-red)',
    green: 'var(--color-green)',
    amber: 'var(--color-amber)',
  };

  return (
    <div className="card px-5 py-4">
      <div className="flex items-center gap-3">
        <div
          className="flex h-9 w-9 items-center justify-center rounded-btn"
          style={{ background: accentMap[accent], color: colorMap[accent] }}
        >
          {icon}
        </div>
        <div>
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
          <p className="text-xs text-[var(--text-muted)]">{label}</p>
        </div>
      </div>
    </div>
  );
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    running: '进行中',
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
  if (status === 'partial') return 'badge-warning';
  return 'badge-danger';
}

export default function Dashboard() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [totalRules, setTotalRules] = useState(0);
  const [highRisk, setHighRisk] = useState(0);

  useEffect(() => {
    fetchBatches().then(setBatches).catch(() => {});
    fetchRules({ page_size: 1 }).then((res) => setTotalRules(res.total)).catch(() => {});
    fetchRules({ risk_level: '高', page_size: 1 }).then((res) => setHighRisk(res.total)).catch(() => {});
  }, []);

  const recent = batches.slice(0, 5);

  return (
    <div className="animate-page-in space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">规则管理平台概览</p>
        </div>
        <Link to="/tasks/new" className="btn-primary">
          <Plus size={16} />
          新建任务
        </Link>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-4 animate-stagger">
        <MetricCard label="规则总量" value={totalRules} icon={<TrendingUp size={18} />} accent="blue" />
        <MetricCard label="高风险规则" value={highRisk} icon={<AlertTriangle size={18} />} accent="red" />
        <MetricCard label="本周任务" value={batches.length} icon={<Plus size={18} />} accent="green" />
        <MetricCard label="Dify 集成" value="在线" icon={<Link2 size={18} />} accent="amber" />
      </div>

      {/* Recent tasks */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[17px] font-semibold">最近任务</h2>
          <Link to="/tasks" className="text-sm text-[var(--color-blue)] hover:underline">
            查看全部
          </Link>
        </div>
        {recent.length === 0 ? (
          <div className="card px-6 py-12 text-center">
            <p className="text-[var(--text-muted)]">暂无任务</p>
            <Link to="/tasks/new" className="mt-3 inline-block text-sm text-[var(--color-blue)]">
              创建第一个任务 →
            </Link>
          </div>
        ) : (
          <div className="space-y-2 animate-stagger">
            {recent.map((batch) => (
              <Link
                key={batch.batch_id}
                to={`/tasks/${batch.batch_id}`}
                className="card card-hover flex items-center justify-between px-5 py-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{batch.batch_id}</p>
                  <p className="mt-0.5 text-xs text-[var(--text-muted)]">
                    {batch.total_files ?? 0} 个文件 · {batch.started_at?.slice(0, 10)}
                  </p>
                </div>
                <span className={statusBadgeClass(batch.status)}>{statusLabel(batch.status)}</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
