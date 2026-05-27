import type { BatchProgress, PipelineFileState, PipelineState } from '../api';

const PIPELINE_ORDER = ['P1', 'P2', 'P3', 'P4', 'P5', 'direct'];

function pct(done: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return String(value);
}

function StatusText({ status, reason }: { status: string; reason?: string | null }) {
  const map: Record<string, { label: string; className: string }> = {
    pending: { label: '等待中', className: 'text-gray-400' },
    running: { label: '运行中', className: 'text-primary' },
    done: { label: '完成', className: 'text-emerald-600' },
    skipped: { label: reason ? `跳过: ${reason}` : '已跳过', className: 'text-gray-400' },
    failed: { label: reason ? `失败: ${reason}` : '失败', className: 'text-red-600' },
  };
  const config = map[status] || { label: status, className: 'text-gray-500' };
  return <span className={`text-xs font-medium ${config.className}`}>{config.label}</span>;
}

function FileCell({ state }: { state?: PipelineFileState }) {
  if (!state) {
    return <span className="text-xs text-gray-300">-</span>;
  }
  if (state.status === 'skipped') {
    return (
      <div className="min-w-[112px]">
        <StatusText status="skipped" reason={state.skip_reason} />
      </div>
    );
  }
  if (state.status === 'failed') {
    return (
      <div className="min-w-[112px]">
        <StatusText status="failed" reason={state.skip_reason} />
      </div>
    );
  }
  const percent = pct(state.blocks_done, state.blocks_total);
  const barClass = state.status === 'done' ? 'bg-emerald-500' : 'bg-primary';
  return (
    <div className="min-w-[132px]">
      <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
        <span>{percent}%</span>
        <span>{state.blocks_done}/{state.blocks_total} 块</span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-1.5 rounded-full ${barClass}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="text-[11px] text-gray-400 mt-1">{state.rules_emitted} 条</div>
    </div>
  );
}

function rowStatus(state: PipelineState): string {
  if (state.status === 'running') return '运行中';
  if (state.status === 'done') return '完成';
  if (state.status === 'failed') return '失败';
  if (state.status === 'skipped') return '已跳过';
  return '等待中';
}

interface PipelineProgressProps {
  progress: BatchProgress | null;
  tokensBudget: number;
}

export default function PipelineProgress({ progress, tokensBudget }: PipelineProgressProps) {
  const pipelineProgress = progress?.pipeline_progress || {};
  const firstWithFiles = Object.values(pipelineProgress).find((state) => state.files);
  const filenames = Object.keys(firstWithFiles?.files || {});
  const fidelity = progress?.fidelity_stats || {
    intercepted: 0,
    placeholders: 0,
    discarded: 0,
    voice_mismatch: 0,
  };
  const tokenRatio = tokensBudget > 0 ? (progress?.tokens_used || 0) / tokensBudget : 0;
  const tokenClass =
    tokenRatio >= 1 ? 'text-red-600' : tokenRatio >= 0.8 ? 'text-amber-600' : 'text-gray-500';

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-air-border flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">智能体审查进度</h2>
          <div className="text-xs text-gray-400 mt-0.5">
            {progress?.current_step || '等待启动'}
          </div>
        </div>
        <div className={`text-sm font-mono ${tokenClass}`}>
          Token: {formatTokens(progress?.tokens_used || 0)} / {formatTokens(tokensBudget)}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="bg-gray-50/70 border-b border-air-border">
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Pipeline</th>
              {filenames.map((filename, index) => (
                <th key={filename} className="px-4 py-3 text-left text-xs font-medium text-gray-400">
                  <div className="max-w-[160px] truncate" title={filename}>
                    文件{index + 1}
                  </div>
                </th>
              ))}
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">规则产出</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-air-border">
            {PIPELINE_ORDER.map((id) => {
              const state = pipelineProgress[id];
              return (
                <tr key={id} className="hover:bg-air-hover">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900">
                      {id === 'direct' ? 'Direct' : id} {state?.label || ''}
                    </div>
                  </td>
                  {filenames.map((filename) => (
                    <td key={filename} className="px-4 py-3 align-top">
                      <FileCell state={state?.files?.[filename]} />
                    </td>
                  ))}
                  <td className="px-4 py-3 text-sm font-mono text-gray-700">
                    {state?.rules_emitted ?? 0}
                  </td>
                  <td className="px-4 py-3">
                    <StatusText status={state?.status || 'pending'} reason={state?.skip_reason} />
                    <div className="text-[11px] text-gray-400 mt-0.5">{state ? rowStatus(state) : '-'}</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 border-t border-air-border bg-gray-50/60 flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-500">
        <span>忠实度门拦截: {fidelity.intercepted} 条</span>
        <span>占位规则: {fidelity.placeholders} 条</span>
        <span>弃用: {fidelity.discarded} 条</span>
        <span>语态不匹配: {fidelity.voice_mismatch} 条</span>
      </div>
    </div>
  );
}
