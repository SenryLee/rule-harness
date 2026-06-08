import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Download, CheckCircle2 } from 'lucide-react';
import { fetchBatch, fetchBatchRules, subscribeBatchProgress, applyMerge, downloadExport } from '../api';
import type { Batch, RuleItem, BatchProgress, ExportKind } from '../api';

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

function riskBadge(level: string) {
  if (level === '高') return 'badge-danger';
  if (level === '中') return 'badge-warning';
  return 'badge-success';
}

const EXPORTS: { key: ExportKind; label: string }[] = [
  { key: 'main-csv', label: '主 CSV' },
  { key: 'metadata-csv', label: '元数据' },
  { key: 'conflict-report', label: '冲突报告' },
  { key: 'placeholders-csv', label: '占位规则' },
  { key: 'negotiation-csv', label: '谈判阶梯' },
  { key: 'template-strategy', label: '模板策略' },
];

export default function TaskDetail() {
  const { batchId } = useParams<{ batchId: string }>();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    if (!batchId) return;

    fetchBatch(batchId).then(setBatch).catch(() => {});
    fetchBatchRules(batchId, { page_size: 50 }).then((res) => {
      setRules(res.rules);
      setTotal(res.total);
    }).catch(() => {});

    // Subscribe to progress if running
    const unsub = subscribeBatchProgress(
      batchId,
      (p) => setProgress(p),
      () => {
        // Refresh batch and rules on completion
        fetchBatch(batchId).then(setBatch).catch(() => {});
        fetchBatchRules(batchId, { page_size: 50 }).then((res) => {
          setRules(res.rules);
          setTotal(res.total);
        }).catch(() => {});
      },
    );

    return unsub;
  }, [batchId]);

  const isRunning = batch?.status === 'running';
  const isDone = batch?.status === 'success' || batch?.status === 'partial' || batch?.status === 'merged';

  const handleApply = async () => {
    if (!batchId) return;
    try {
      await applyMerge(batchId);
      fetchBatch(batchId).then(setBatch).catch(() => {});
    } catch {
      // ignore
    }
  };

  if (!batchId) return null;

  return (
    <div className="animate-page-in space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/tasks" className="btn-ghost">
          <ArrowLeft size={16} />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight font-mono">{batchId}</h1>
          <p className="mt-0.5 text-sm text-[var(--text-muted)]">
            {batch ? statusLabel(batch.status) : '加载中...'}
            {batch?.started_at && ` · ${batch.started_at.slice(0, 16).replace('T', ' ')}`}
          </p>
        </div>
        {isDone && batch?.status !== 'merged' && (
          <button className="btn-primary" onClick={handleApply}>
            <CheckCircle2 size={16} /> 应用入库
          </button>
        )}
      </div>

      {/* Progress (when running) */}
      {isRunning && progress && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">{progress.current_step || '处理中...'}</span>
            <span className="text-[var(--text-muted)]">
              {progress.processed_files}/{progress.total_files} 文件 · {progress.total_rules} 条规则
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-[var(--color-gray-5)] overflow-hidden">
            <div
              className="h-full rounded-full bg-[var(--color-blue)] transition-all duration-500"
              style={{ width: `${progress.total_files ? (progress.processed_files / progress.total_files * 100) : 0}%` }}
            />
          </div>
          {progress.errors.length > 0 && (
            <div className="text-xs text-[var(--color-red)]">
              {progress.errors[progress.errors.length - 1]}
            </div>
          )}
        </div>
      )}

      {/* Export buttons */}
      {isDone && (
        <div className="flex items-center gap-2 flex-wrap">
          {EXPORTS.map(({ key, label }) => (
            <button
              key={key}
              className="btn-secondary text-xs"
              onClick={() => downloadExport(batchId, key)}
            >
              <Download size={14} /> {label}
            </button>
          ))}
        </div>
      )}

      {/* Rules table */}
      {isDone && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-[var(--border-light)]">
            <p className="text-sm font-medium">抽取结果 · {total} 条规则</p>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-light)] text-left text-xs font-medium text-[var(--text-muted)]">
                <th className="px-5 py-3">风险</th>
                <th className="px-5 py-3">检查项</th>
                <th className="px-5 py-3">审查要求</th>
                <th className="px-5 py-3">置信度</th>
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 ? (
                <tr><td colSpan={4} className="px-5 py-8 text-center text-[var(--text-muted)]">暂无规则</td></tr>
              ) : (
                rules.map((rule) => (
                  <tr key={rule.rule_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors">
                    <td className="px-5 py-4">
                      <span className={riskBadge(rule.risk_level)}>{rule.risk_level}</span>
                    </td>
                    <td className="px-5 py-4 font-medium max-w-[280px] truncate">{rule.check_item}</td>
                    <td className="px-5 py-4 text-[var(--text-secondary)] max-w-[320px] truncate">{rule.requirement}</td>
                    <td className="px-5 py-4 font-mono text-xs">
                      {rule.combined_confidence != null ? (rule.combined_confidence * 100).toFixed(0) + '%' : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
