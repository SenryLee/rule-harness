import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  applyMerge,
  downloadExport,
  fetchBatchRules,
} from '../api';
import type { RuleItem } from '../api';

type ResultsTab = 'main' | 'placeholder' | 'discarded' | 'negotiation';

interface ResultsViewProps {
  batchId: string;
  refreshKey: number;
}

const TABS: Array<{ key: ResultsTab; label: string }> = [
  { key: 'main', label: '实质规则' },
  { key: 'placeholder', label: '占位' },
  { key: 'discarded', label: '弃用' },
  { key: 'negotiation', label: '谈判阶梯' },
];

function RiskBadge({ level }: { level?: string }) {
  const map: Record<string, string> = {
    高: 'badge-danger',
    中: 'badge-warning',
    低: 'badge-success',
    high: 'badge-danger',
    medium: 'badge-warning',
    low: 'badge-success',
  };
  const label: Record<string, string> = { high: '高', medium: '中', low: '低' };
  return <span className={map[level || ''] || 'badge-info'}>{label[level || ''] || level || '-'}</span>;
}

function ConfidenceBar({ value }: { value?: number }) {
  if (value == null) return <span className="text-gray-400 text-sm">-</span>;
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-primary' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-gray-200 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-500 w-8">{pct}%</span>
    </div>
  );
}

function pctText(numerator: number, denominator: number): string {
  if (!denominator) return '0%';
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function targetOf(rule: RuleItem): ResultsTab {
  const target = rule.output_target || 'main';
  if (target === 'placeholder' || target === 'discarded' || target === 'negotiation') return target;
  return 'main';
}

export default function ResultsView({ batchId, refreshKey }: ResultsViewProps) {
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ResultsTab>('main');
  const [selectedRule, setSelectedRule] = useState<RuleItem | null>(null);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchBatchRules(batchId, { page_size: 1000 })
      .then((res) => {
        if (!cancelled) setRules(res.rules);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, refreshKey]);

  const counts = useMemo(() => {
    const next: Record<ResultsTab, number> = {
      main: 0,
      placeholder: 0,
      discarded: 0,
      negotiation: 0,
    };
    rules.forEach((rule) => {
      next[targetOf(rule)] += 1;
    });
    return next;
  }, [rules]);

  const visibleRules = useMemo(
    () => rules.filter((rule) => targetOf(rule) === activeTab),
    [activeTab, rules],
  );

  const summary = useMemo(() => {
    const total = rules.length;
    const main = counts.main;
    const high = rules.filter((rule) => rule.risk_level === '高' || rule.risk_level === 'high').length;
    const conflicts = rules.filter((rule) => rule.conflict_flag && rule.conflict_flag !== '无').length;
    const needsReview = rules.filter((rule) => (rule.combined_confidence ?? rule.confidence ?? 1) < 0.7 || (rule.conflict_flag && rule.conflict_flag !== '无')).length;
    const fidelityPass = rules.filter((rule) => rule.fidelity_pass !== false).length;
    const voiceMatch = rules.filter((rule) => rule.voice_match !== false).length;
    return {
      total,
      main,
      high,
      conflicts,
      needsReview,
      fidelityRate: pctText(fidelityPass, total),
      voiceRate: pctText(voiceMatch, total),
      placeholderRate: pctText(counts.placeholder, total),
      discardedRate: pctText(counts.discarded, total),
    };
  }, [counts, rules]);

  const handleApplyMerge = useCallback(async () => {
    if (!confirm('确认将本批次规则合并到主规则库？此操作不可撤销。')) return;
    setApplying(true);
    try {
      await applyMerge(batchId);
      alert('已成功合并到主规则库');
    } catch (err) {
      alert(err instanceof Error ? err.message : '合并失败');
    } finally {
      setApplying(false);
    }
  }, [batchId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3 animate-fade-in">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-air-border border-t-primary" />
        <span className="text-gray-400 text-sm">加载审查结果...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6 border-red-200 bg-red-50">
        <div className="text-sm font-semibold text-red-600">加载失败</div>
        <div className="text-sm text-gray-600 mt-1">{error}</div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in pb-24 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl text-gray-900">审查结果</h1>
          <div className="font-mono text-sm text-gray-400 mt-1">{batchId}</div>
        </div>
      </div>

      <div className="card p-5 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Metric label="实质规则" value={summary.main} />
          <Metric label="高风险" value={summary.high} tone="danger" />
          <Metric label="需复核" value={summary.needsReview} tone="warning" />
          <Metric label="冲突数" value={summary.conflicts} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-4 border-t border-air-border">
          <Metric label="忠实度通过率" value={summary.fidelityRate} />
          <Metric label="语态匹配率" value={summary.voiceRate} />
          <Metric label="占位规则比例" value={summary.placeholderRate} />
          <Metric label="弃用规则" value={`${counts.discarded} (${summary.discardedRate})`} tone="danger" />
        </div>
      </div>

      <div className="card overflow-hidden mb-6">
        <div className="flex border-b border-air-border bg-white">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-primary text-primary bg-primary-soft'
                  : 'border-transparent text-gray-500 hover:text-gray-800 hover:bg-air-hover'
              }`}
            >
              {tab.label} ({counts[tab.key]})
            </button>
          ))}
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-air-border">
            <thead>
              <tr className="bg-gray-50/50">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">规则ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">风险</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">检查项</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">审查要求</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">管道</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">置信度</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">校验</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-air-border">
              {visibleRules.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-gray-400">
                    当前分类暂无规则
                  </td>
                </tr>
              ) : (
                visibleRules.map((rule) => (
                  <tr key={rule.rule_id} className="hover:bg-air-hover cursor-pointer" onClick={() => setSelectedRule(rule)}>
                    <td className="px-4 py-3 text-sm font-mono text-gray-400 whitespace-nowrap">{rule.rule_id}</td>
                    <td className="px-4 py-3"><RiskBadge level={rule.risk_level} /></td>
                    <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">{rule.check_item}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-md truncate">{rule.requirement}</td>
                    <td className="px-4 py-3"><span className="badge-accent">{rule.pipeline || '-'}</span></td>
                    <td className="px-4 py-3"><ConfidenceBar value={rule.combined_confidence ?? rule.confidence} /></td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      <div>{rule.fidelity_pass === false ? '忠实度失败' : '忠实度通过'}</div>
                      <div>{rule.voice_match === false ? '语态不匹配' : '语态匹配'}</div>
                    </td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={(event) => { event.stopPropagation(); setSelectedRule(rule); }} className="text-primary hover:text-primary-hover text-sm font-medium">
                        详情
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="sticky bottom-0 z-20 bg-white/90 backdrop-blur-sm border border-air-border rounded-card shadow-popover px-6 py-3 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-400 mr-2">导出:</span>
          <ExportButton label="主CSV" onClick={() => downloadExport(batchId, 'main-csv')} />
          <ExportButton label="占位CSV" onClick={() => downloadExport(batchId, 'placeholders-csv')} />
          <ExportButton label="弃用CSV" onClick={() => downloadExport(batchId, 'discarded-csv')} />
          <ExportButton label="谈判CSV" onClick={() => downloadExport(batchId, 'negotiation-csv')} />
          <ExportButton label="元数据CSV" onClick={() => downloadExport(batchId, 'metadata-csv')} />
          <ExportButton label="冲突HTML" onClick={() => downloadExport(batchId, 'conflict-report')} />
          <ExportButton label="变更集CSV" onClick={() => downloadExport(batchId, 'change-set')} />
        </div>
        <button type="button" onClick={handleApplyMerge} disabled={applying} className="btn-primary text-sm">
          {applying ? '合并中...' : '应用变更入库'}
        </button>
      </div>

      {selectedRule && <DetailDrawer rule={selectedRule} onClose={() => setSelectedRule(null)} />}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string | number; tone?: 'danger' | 'warning' }) {
  const color = tone === 'danger' ? 'text-red-500' : tone === 'warning' ? 'text-amber-500' : 'text-gray-900';
  return (
    <div>
      <div className={`font-mono text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-400 mt-1">{label}</div>
    </div>
  );
}

function ExportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="btn-secondary text-xs py-1.5 px-3">
      {label}
    </button>
  );
}

function DetailDrawer({ rule, onClose }: { rule: RuleItem; onClose: () => void }) {
  const failures = rule.fidelity_failures || [];
  const ladder = rule.ladder || {};
  const ladderPreferred = rule.ladder_preferred || ladder.preferred;
  const ladderAcceptable = rule.ladder_acceptable || ladder.acceptable;
  const ladderUnacceptable = rule.ladder_unacceptable || ladder.unacceptable;

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-fade-in">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-[560px] bg-white shadow-xl overflow-y-auto h-full animate-slide-in">
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-air-border px-6 py-4 flex items-center justify-between">
          <h3 className="font-display text-lg text-gray-900">规则详情</h3>
          <button type="button" onClick={onClose} className="btn-ghost text-sm py-1 px-2">关闭</button>
        </div>
        <div className="px-6 py-4 space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <Info label="规则ID" value={rule.rule_id} mono />
            <div><div className="text-xs text-gray-400 mb-1">风险级别</div><RiskBadge level={rule.risk_level} /></div>
            <Info label="管道" value={rule.pipeline || '-'} />
            <Info label="输出桶" value={rule.output_target || 'main'} />
            <Info label="合同类型" value={rule.contract_types?.join('、') || '-'} />
            <Info label="来源类别" value={rule.source_tag || '-'} />
          </div>

          <Section title="检查项">{rule.check_item || '-'}</Section>
          <Section title="审查要求">{rule.requirement || '-'}</Section>
          {rule.notes && <Section title="备注">{rule.notes}</Section>}

          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-2">校验结果</div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Info label="忠实度" value={rule.fidelity_pass === false ? '未通过' : '通过'} />
              <Info label="语态匹配" value={rule.voice_match === false ? '不匹配' : '匹配'} />
              <Info label="结构校验" value={rule.struct_check_pass === false ? '未通过' : '通过'} />
              <div>
                <div className="text-xs text-gray-400 mb-1">综合置信度</div>
                <ConfidenceBar value={rule.combined_confidence ?? rule.confidence} />
              </div>
            </div>
            {failures.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {failures.map((failure) => (
                  <span key={failure} className="badge-danger">{failure}</span>
                ))}
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-air-border">
            <div className="text-xs text-gray-400 mb-1.5">原文锚点</div>
            <div className="text-sm text-gray-600 font-mono mb-2">{rule.source_location || '-'}</div>
            <div className="bg-air-muted rounded-input p-4 text-sm text-gray-700 leading-relaxed border border-air-border whitespace-pre-wrap">
              {rule.source_excerpt || '-'}
            </div>
          </div>

          {(ladderPreferred || ladderAcceptable || ladderUnacceptable) && (
            <div className="pt-4 border-t border-air-border space-y-3">
              <div className="text-xs text-gray-400">谈判阶梯</div>
              {ladderPreferred && <LadderRow label="首选" value={ladderPreferred} color="bg-emerald-500" />}
              {ladderAcceptable && <LadderRow label="可接受" value={ladderAcceptable} color="bg-amber-500" />}
              {ladderUnacceptable && <LadderRow label="不可接受" value={ladderUnacceptable} color="bg-red-500" />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-sm text-gray-700 ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="pt-4 border-t border-air-border">
      <div className="text-xs text-gray-400 mb-1.5">{title}</div>
      <div className="text-sm text-gray-900 whitespace-pre-wrap leading-relaxed">{children}</div>
    </div>
  );
}

function LadderRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex gap-3">
      <div className={`w-1 self-stretch rounded-full ${color}`} />
      <div>
        <div className="text-xs font-medium text-gray-400 mb-0.5">{label}</div>
        <div className="text-sm text-gray-900 whitespace-pre-wrap">{value}</div>
      </div>
    </div>
  );
}
