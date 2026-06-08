import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Download, CheckCircle2, Sparkles, X, Loader2 } from 'lucide-react';
import {
  fetchBatch,
  fetchBatchRules,
  subscribeBatchProgress,
  applyMerge,
  downloadExport,
  generateSkill,
  downloadSkillZip,
} from '../api';
import type { Batch, RuleItem, BatchProgress, ExportKind, SkillGenerateResponse } from '../api';

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

const STEP_LABELS: Record<string, string> = {
  queued: '排队中',
  parsing: '解析文档',
  extracting: '抽取规则',
  finalizing: '去重与校验',
  merging: '合并比对',
  exporting: '生成导出',
  persisting: '写入存储',
  done: '完成',
};

/**
 * 把后端的多阶段进度折算成单调递增的总进度百分比。
 * 解析 3-15%，抽取 15-90%（按区块粒度），收尾 90-99%，完成 100%。
 * 这样解析阶段不会瞬间打满，抽取这一最耗时阶段能真实体现推进。
 */
function overallProgress(p: BatchProgress): number {
  const step = p.current_step;
  const fileFrac = p.total_files ? p.processed_files / p.total_files : 0;
  const blockFrac = p.total_blocks ? p.processed_blocks / p.total_blocks : 0;
  switch (step) {
    case 'queued':
      return 2;
    case 'parsing':
      return 3 + fileFrac * 12;
    case 'extracting':
      return 15 + blockFrac * 75;
    case 'finalizing':
      return 91;
    case 'merging':
      return 94;
    case 'exporting':
      return 97;
    case 'persisting':
      return 99;
    case 'done':
      return 100;
    default:
      return Math.max(fileFrac, blockFrac) * 90;
  }
}

function riskBadge(level: string) {
  if (level === '高' || level === 'high') return 'badge-danger';
  if (level === '中' || level === 'medium') return 'badge-warning';
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
  const [selectedRule, setSelectedRule] = useState<RuleItem | null>(null);
  const [skillOpen, setSkillOpen] = useState(false);

  // 进度条单调递增：抽取期 SSE 偶发抖动时不回退
  const [displayPct, setDisplayPct] = useState(0);
  const maxPctRef = useRef(0);

  useEffect(() => {
    if (!batchId) return;

    maxPctRef.current = 0;
    setDisplayPct(0);

    const loadRules = () =>
      fetchBatchRules(batchId, { page_size: 1000 })
        .then((res) => {
          setRules(res.rules);
          setTotal(res.total);
        })
        .catch(() => {});

    fetchBatch(batchId).then(setBatch).catch(() => {});
    loadRules();

    const unsub = subscribeBatchProgress(
      batchId,
      (p) => {
        setProgress(p);
        const next = Math.min(100, Math.max(maxPctRef.current, overallProgress(p)));
        maxPctRef.current = next;
        setDisplayPct(next);
      },
      () => {
        maxPctRef.current = 100;
        setDisplayPct(100);
        fetchBatch(batchId).then(setBatch).catch(() => {});
        loadRules();
      },
    );

    return unsub;
  }, [batchId]);

  const isRunning = batch?.status === 'running' || progress?.status === 'running';
  const isDone =
    batch?.status === 'success' || batch?.status === 'partial' || batch?.status === 'merged';

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

  // 抽取阶段拿不到区块总数时（如全为红线/案例文件）走不确定态动画
  const indeterminate =
    isRunning && progress?.current_step === 'extracting' && !progress?.total_blocks;

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
        {isDone && (
          <button className="btn-secondary" onClick={() => setSkillOpen(true)}>
            <Sparkles size={16} /> 生成 Skill
          </button>
        )}
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
            <span className="font-medium">
              {STEP_LABELS[progress.current_step] || progress.current_step || '处理中...'}
            </span>
            <span className="text-[var(--text-muted)]">
              {progress.processed_files}/{progress.total_files} 文件 · {progress.total_rules} 条规则
              {!indeterminate && ` · ${displayPct.toFixed(0)}%`}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-[var(--color-gray-5)] overflow-hidden">
            {indeterminate ? (
              <div className="h-full w-1/3 rounded-full bg-[var(--color-blue)] animate-indeterminate" />
            ) : (
              <div
                className="h-full rounded-full bg-[var(--color-blue)] transition-all duration-500"
                style={{ width: `${displayPct}%` }}
              />
            )}
          </div>
          {progress.current_step === 'extracting' && progress.total_blocks > 0 && (
            <div className="text-xs text-[var(--text-muted)]">
              已处理 {progress.processed_blocks}/{progress.total_blocks} 个文本块
            </div>
          )}
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
            <p className="text-sm font-medium">
              抽取结果 · {total} 条规则
              <span className="ml-2 text-xs font-normal text-[var(--text-muted)]">
                点击任意行查看完整内容
              </span>
            </p>
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
                <tr>
                  <td colSpan={4} className="px-5 py-8 text-center text-[var(--text-muted)]">
                    暂无规则
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr
                    key={rule.rule_id}
                    onClick={() => setSelectedRule(rule)}
                    className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors cursor-pointer"
                  >
                    <td className="px-5 py-4">
                      <span className={riskBadge(rule.risk_level)}>{rule.risk_level}</span>
                    </td>
                    <td className="px-5 py-4 font-medium max-w-[280px] truncate">{rule.check_item}</td>
                    <td className="px-5 py-4 text-[var(--text-secondary)] max-w-[320px] truncate">
                      {rule.requirement}
                    </td>
                    <td className="px-5 py-4 font-mono text-xs">
                      {rule.combined_confidence != null
                        ? (rule.combined_confidence * 100).toFixed(0) + '%'
                        : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {selectedRule && <DetailDrawer rule={selectedRule} onClose={() => setSelectedRule(null)} />}
      {skillOpen && <SkillModal batchId={batchId} onClose={() => setSkillOpen(false)} />}
    </div>
  );
}

// ── Skill 生成弹窗 ──────────────────────────────────────────────────────

function SkillModal({ batchId, onClose }: { batchId: string; onClose: () => void }) {
  const [domain, setDomain] = useState('');
  const [parties, setParties] = useState(['甲方', '乙方']);
  const [drafting, setDrafting] = useState(true);
  const [llm, setLlm] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<SkillGenerateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (!domain.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await generateSkill(batchId, {
        domain_name: domain.trim(),
        party_perspectives: parties.filter(Boolean),
        include_drafting: drafting,
        llm_enhance: llm,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-page-in">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-[520px] max-w-[92vw] bg-white rounded-2xl shadow-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-[var(--border-light)] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--color-blue)] text-white flex items-center justify-center">
              <Sparkles size={18} />
            </div>
            <div>
              <div className="text-base font-semibold">生成 Skill 压缩包</div>
              <div className="text-xs text-[var(--text-muted)]">打包为可部署的法务 AI 平台 Skill</div>
            </div>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost p-1">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {result ? (
            <div className="p-5 bg-[var(--color-green-soft)] border border-[var(--border-light)] rounded-xl text-center">
              <div className="w-12 h-12 mx-auto rounded-full bg-[var(--color-green)] text-white flex items-center justify-center mb-3">
                <CheckCircle2 size={24} />
              </div>
              <div className="text-base font-semibold text-[var(--color-green)]">生成完成</div>
              <div className="text-sm text-[var(--text-secondary)] mt-1">
                {result.file_count} 个文件已打包
              </div>
              <button
                type="button"
                onClick={() => downloadSkillZip(batchId)}
                className="btn-primary mt-4 mx-auto"
              >
                <Download size={16} /> 下载 ZIP 压缩包
              </button>
            </div>
          ) : (
            <>
              <label className="block text-xs text-[var(--text-muted)]">
                合同领域名称 *
                <input
                  autoFocus
                  type="text"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="例如：采购合同、股权转让协议、赠与合同"
                  className="input-field text-sm mt-1"
                />
              </label>
              <label className="block text-xs text-[var(--text-muted)]">
                主体立场（逗号分隔）
                <input
                  type="text"
                  value={parties.join(', ')}
                  onChange={(e) =>
                    setParties(
                      e.target.value
                        .split(/[,，]/)
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                  placeholder="甲方, 乙方"
                  className="input-field text-sm mt-1"
                />
              </label>
              <div className="flex items-center gap-5">
                <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)] cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={drafting}
                    onChange={(e) => setDrafting(e.target.checked)}
                  />
                  包含起草模式
                </label>
                <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)] cursor-pointer select-none">
                  <input type="checkbox" checked={llm} onChange={(e) => setLlm(e.target.checked)} />
                  <Sparkles size={14} className="text-[var(--color-blue)]" />
                  LLM 增强
                </label>
              </div>
              {error && (
                <div className="p-3 bg-[var(--color-red-soft)] border border-[var(--border-light)] rounded-lg text-sm text-[var(--color-red)]">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {!result && (
          <div className="px-6 py-4 border-t border-[var(--border-light)] flex justify-end">
            <button
              type="button"
              onClick={handleGenerate}
              disabled={generating || !domain.trim()}
              className="btn-primary disabled:opacity-40"
            >
              {generating ? (
                <>
                  <Loader2 size={16} className="animate-spin" /> 生成中...
                </>
              ) : (
                <>
                  <Sparkles size={16} /> 生成并打包
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 规则完整内容预览（详情抽屉）────────────────────────────────────────

function fieldValue(value: string | null | undefined): string | null {
  const text = value?.trim();
  return text || null;
}

function DetailDrawer({ rule, onClose }: { rule: RuleItem; onClose: () => void }) {
  const failures = rule.fidelity_failures || [];
  const ladder = rule.ladder || {};
  const ladderPreferred = rule.ladder_preferred || ladder.preferred;
  const ladderAcceptable = rule.ladder_acceptable || ladder.acceptable;
  const ladderUnacceptable = rule.ladder_unacceptable || ladder.unacceptable;
  const deepAnalysisRows = [
    { label: '适用假设', value: fieldValue(rule.assumption) },
    { label: '行为模式', value: fieldValue(rule.behavior_mode) },
    { label: '后果', value: fieldValue(rule.consequence) },
    { label: '例外条件', value: fieldValue(rule.exception_conditions) },
    { label: '审查动作', value: fieldValue(rule.review_action) },
    { label: '转换说明', value: fieldValue(rule.transformation_note) },
  ].filter((row) => row.value);

  const confidence = rule.combined_confidence ?? rule.confidence;

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-page-in">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-[560px] max-w-[94vw] bg-white shadow-xl overflow-y-auto h-full">
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-[var(--border-light)] px-6 py-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">规则详情</h3>
          <button type="button" onClick={onClose} className="btn-ghost p-1">
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-5">
          <div className="grid grid-cols-2 gap-4">
            <Info label="规则ID" value={rule.rule_id} mono />
            <div>
              <div className="text-xs text-[var(--text-muted)] mb-1">风险级别</div>
              <span className={riskBadge(rule.risk_level)}>{rule.risk_level}</span>
            </div>
            <Info label="管道" value={rule.pipeline || '-'} />
            <Info label="输出桶" value={rule.output_target || 'main'} />
            <Info label="任务模式" value={rule.task_mode || 'full_library'} />
            <Info label="范围匹配" value={rule.scope_match || 'in_scope'} />
            <Info label="合同类型" value={rule.contract_types?.join('、') || '-'} />
            <Info label="来源类别" value={rule.source_tag || '-'} />
          </div>

          <Section title="检查项">{rule.check_item || '-'}</Section>
          <Section title="审查要求">{rule.requirement || '-'}</Section>
          {rule.notes && <Section title="备注">{rule.notes}</Section>}

          {deepAnalysisRows.length > 0 && (
            <div className="pt-4 border-t border-[var(--border-light)]">
              <div className="text-xs text-[var(--text-muted)] mb-2">深度分析</div>
              <div className="space-y-3">
                {deepAnalysisRows.map((row) => (
                  <div key={row.label}>
                    <div className="text-xs text-[var(--text-muted)] mb-0.5">{row.label}</div>
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">{row.value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(rule.scope_reason || rule.template_anchor) && (
            <Section title="范围依据">
              {[rule.scope_reason, rule.template_anchor ? `模板锚点：${rule.template_anchor}` : '']
                .filter(Boolean)
                .join('\n')}
            </Section>
          )}

          <div className="pt-4 border-t border-[var(--border-light)]">
            <div className="text-xs text-[var(--text-muted)] mb-2">校验结果</div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Info label="忠实度" value={rule.fidelity_pass === false ? '未通过' : '通过'} />
              <Info label="语态匹配" value={rule.voice_match === false ? '不匹配' : '匹配'} />
              <Info label="结构校验" value={rule.struct_check_pass === false ? '未通过' : '通过'} />
              <Info
                label="综合置信度"
                value={confidence != null ? (confidence * 100).toFixed(0) + '%' : '—'}
                mono
              />
            </div>
            {failures.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {failures.map((failure) => (
                  <span key={failure} className="badge-danger">
                    {failure}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-[var(--border-light)]">
            <div className="text-xs text-[var(--text-muted)] mb-1.5">原文锚点</div>
            <div className="text-sm text-[var(--text-muted)] font-mono mb-2">
              {rule.source_location || '-'}
            </div>
            <div className="bg-[var(--color-gray-5)] rounded-lg p-4 text-sm text-[var(--text-secondary)] leading-relaxed border border-[var(--border-light)] whitespace-pre-wrap">
              {rule.source_excerpt || '-'}
            </div>
          </div>

          {(ladderPreferred || ladderAcceptable || ladderUnacceptable) && (
            <div className="pt-4 border-t border-[var(--border-light)] space-y-3">
              <div className="text-xs text-[var(--text-muted)]">谈判阶梯</div>
              {ladderPreferred && (
                <LadderRow label="首选" value={ladderPreferred} color="var(--color-green)" />
              )}
              {ladderAcceptable && (
                <LadderRow label="可接受" value={ladderAcceptable} color="#c97b00" />
              )}
              {ladderUnacceptable && (
                <LadderRow label="不可接受" value={ladderUnacceptable} color="var(--color-red)" />
              )}
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
      <div className="text-xs text-[var(--text-muted)] mb-1">{label}</div>
      <div className={`text-sm text-[var(--text-secondary)] ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="pt-4 border-t border-[var(--border-light)]">
      <div className="text-xs text-[var(--text-muted)] mb-1.5">{title}</div>
      <div className="text-sm whitespace-pre-wrap leading-relaxed">{children}</div>
    </div>
  );
}

function LadderRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex gap-3">
      <div className="w-1 self-stretch rounded-full" style={{ background: color }} />
      <div>
        <div className="text-xs font-medium text-[var(--text-muted)] mb-0.5">{label}</div>
        <div className="text-sm whitespace-pre-wrap">{value}</div>
      </div>
    </div>
  );
}
