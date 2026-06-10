import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createBatch,
  fetchBatch,
  fetchConfig,
  previewClassify,
  subscribeBatchProgress,
  updateConfig,
} from '../api';
import type { BatchProgress, Config, CreateBatchMeta, PreviewClassifyResponse } from '../api';
import PipelineProgress from './PipelineProgress';

const EXTRACTION_DOMAINS = [
  { value: '', label: '自动识别', desc: '系统从文件内容推断领域' },
  { value: '通用商事', label: '通用商事', desc: '买卖、采购、销售、服务、代理等' },
  { value: '建工', label: '建设工程', desc: '总包、勘察设计、施工、监理' },
  { value: '房地产', label: '房地产', desc: '商品房、物业、租赁、不动产' },
  { value: '金融', label: '金融', desc: '银行、证券、保险、资管、基金' },
  { value: '医药', label: '医药', desc: '药品、器械、临床、GMP' },
  { value: 'IT', label: '信息技术', desc: '软件、SaaS、数据、网络安全' },
  { value: '制造', label: '制造', desc: '设备、模具、质检、生产线' },
  { value: '能源·电力', label: '能源电力', desc: '光伏、风电、储能、购售电' },
  { value: '股权投资', label: '股权投资', desc: '股权转让、增资、并购、对赌' },
  { value: '劳动人事', label: '劳动人事', desc: '劳动合同、竞业限制、社保' },
];

const PARTY_OPTIONS = ['通用', '甲方', '乙方', '发包人', '承包人', '买方', '卖方', '出租人', '承租人'];

const TASK_MODES = [
  { value: 'full_library', label: '全量规则沉淀' },
  { value: 'template_focused', label: '围绕模板抽取' },
  { value: 'template_strategy', label: '我方模板策略' },
] as const;

// v1.2: 颗粒度档位 1–5（任务级，随本次任务下发，覆盖全局默认）
const GRANULARITY_LABELS: Record<number, { label: string; desc: string }> = {
  1: { label: '粗', desc: '只取强义务/高风险条款，约 0.5–1 条规则/千字' },
  2: { label: '较粗', desc: '稳定口径为主，约 1–2 条/千字' },
  3: { label: '平衡', desc: '默认档位，约 2–4 条/千字' },
  4: { label: '细', desc: '少漏审优先，约 4–6 条/千字' },
  5: { label: '极细', desc: '穷尽式拆解，约 6–10 条/千字' },
};

// 与后端 classifier._map_to_source_tag 保持一致（用于"分类需确认"时一键改选）
const GENRE_TO_SOURCE_TAG: Record<string, string> = {
  '法律法规': '法规',
  '监管与司法文件': '法规',
  '裁判文书': '案例',
  '合同文本': '历史合同',
  '企业内部文件': '内部制度',
  '已有规则库': '标准条款库',
  '专业参考资料': '业务规范',
};

interface UploadedFile {
  id: string;
  file: File;
  meta: CreateBatchMeta;
  classifying: boolean;
  classifyError?: string | null;
  autoClass?: PreviewClassifyResponse | null;
}

import { useApp } from '../context/AppContext';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function progressDone(status?: string): boolean {
  return status === 'success' || status === 'completed' || status === 'partial' || status === 'merged';
}

function defaultMeta(): CreateBatchMeta {
  return {
    source_tag: '历史合同',
    contract_types: [],
    our_party: '通用',
    is_scanned: false,
    jurisdiction: '中国大陆',
  };
}

export default function WorkbenchView() {
  const { state, batchUpdated, refresh: onRefresh } = useApp();
  const { selectedBatch } = state;
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(selectedBatch?.batch_id || null);
  const [progress, setProgress] = useState<BatchProgress | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [configDirty, setConfigDirty] = useState(false);
  const [batchConfigOpen, setBatchConfigOpen] = useState(false);
  const [taskMode, setTaskMode] = useState<CreateBatchMeta['task_mode']>('full_library');
  const [extractionDomain, setExtractionDomain] = useState('');
  const [scopeDescription, setScopeDescription] = useState('');
  // v1.2: 任务级颗粒度档位（不写回全局配置）
  const [granularityLevel, setGranularityLevel] = useState(3);
  const idCounter = useRef(0);

  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        setConfig(cfg);
        setGranularityLevel(
          cfg.extraction.granularity_level
            ?? (cfg.extraction.granularity === 'fine' ? 4 : 3),
        );
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedBatch?.batch_id) {
      setCurrentBatchId(selectedBatch.batch_id);
    } else {
      setCurrentBatchId(null);
      setProgress(null);
      setSubmitError(null);
    }
  }, [selectedBatch?.batch_id]);

  useEffect(() => {
    const batchId = currentBatchId || selectedBatch?.batch_id;
    if (!batchId || progressDone(selectedBatch?.status)) return;

    const cleanup = subscribeBatchProgress(
      batchId,
      (next) => setProgress(next),
      async () => {
        try {
          const detail = await fetchBatch(batchId);
          batchUpdated(detail);
          onRefresh();
        } catch {
          // ignore — batch detail will be fetched on next interaction
        }
      },
    );

    return cleanup;
  }, [currentBatchId, batchUpdated, onRefresh, selectedBatch?.batch_id, selectedBatch?.status]);

  const updateFileMeta = useCallback((id: string, update: Partial<CreateBatchMeta>) => {
    setFiles((prev) =>
      prev.map((item) => (item.id === id ? { ...item, meta: { ...item.meta, ...update } } : item)),
    );
  }, []);

  const classifyFile = useCallback(async (entryId: string, file: File) => {
    try {
      const result = await previewClassify(file);
      setFiles((prev) =>
        prev.map((item) => {
          if (item.id !== entryId) return item;
          const applySource = result.auto_apply_source ?? result.auto_apply ?? false;
          const applyContract = result.auto_apply_contract ?? result.auto_apply ?? false;
          const applyParty = result.auto_apply_party ?? false;
          return {
            ...item,
            classifying: false,
            autoClass: result,
            meta: {
              ...item.meta,
              source_tag: applySource && result.suggested_source_tag
                ? result.suggested_source_tag
                : item.meta.source_tag,
              contract_types: applyContract && result.suggested_contract_types?.length
                ? result.suggested_contract_types.slice(0, 1)
                : item.meta.contract_types,
              our_party: applyParty && result.suggested_our_party
                ? result.suggested_our_party
                : item.meta.our_party,
            },
          };
        }),
      );
    } catch (err) {
      setFiles((prev) =>
        prev.map((item) =>
          item.id === entryId
            ? {
                ...item,
                classifying: false,
                classifyError: err instanceof Error ? err.message : '识别失败，请手动配置',
              }
            : item,
        ),
      );
    }
  }, []);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const entries = Array.from(incoming).map((file) => {
        idCounter.current += 1;
        return {
          id: String(idCounter.current),
          file,
          meta: defaultMeta(),
          classifying: true,
          autoClass: null,
          classifyError: null,
        };
      });
      setFiles((prev) => [...prev, ...entries]);
      entries.forEach((entry) => classifyFile(entry.id, entry.file));
    },
    [classifyFile],
  );

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files);
    },
    [addFiles],
  );

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const canStart = files.length > 0 && files.every((item) => item.meta.source_tag) && !submitting;

  const estimatedTokens = useMemo(() => {
    const size = files.reduce((sum, item) => sum + item.file.size, 0);
    return Math.max(25_000, Math.round(size / 3));
  }, [files]);

  const handleStart = useCallback(async () => {
    if (!canStart) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      // Sync extraction domain to config
      if (config) {
        const updatedConfig = {
          ...config,
          extraction: { ...config.extraction, industry_preset: extractionDomain || null },
        };
        await updateConfig(updatedConfig);
      } else if (config && configDirty) {
        await updateConfig(config);
      }
      // Use classifier results for source_tag, fallback to auto-detected
      const meta = files.map((item) => {
        const clf = item.autoClass?.classification;
        return {
          ...item.meta,
          source_tag: clf?.source_tag || item.meta.source_tag || '历史合同',
          contract_types: extractionDomain ? [extractionDomain] : (item.meta.contract_types || []),
          is_redline: clf?.is_redline || false,
          is_case: clf?.is_case || false,
          task_mode: taskMode,
          scope_description: scopeDescription.trim(),
          granularity_level: granularityLevel,
        };
      });
      const created = await createBatch(files.map((item) => item.file), meta);
      setCurrentBatchId(created.batch_id);
      const detail = await fetchBatch(created.batch_id);
      batchUpdated(detail);
      onRefresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '启动失败');
    } finally {
      setSubmitting(false);
    }
  }, [canStart, config, configDirty, files, batchUpdated, onRefresh, scopeDescription, taskMode, granularityLevel, extractionDomain]);

  const updateExtraction = useCallback((field: 'industry_preset' | 'granularity' | 'regulation_depth', value: string | null) => {
    setConfig((prev) =>
      prev
        ? {
            ...prev,
            extraction: {
              ...prev.extraction,
              [field]: value,
            },
          }
        : prev,
    );
    setConfigDirty(true);
  }, []);

  const tokensBudget = config?.budget.max_tokens_per_batch || 5_000_000;
  const running = !!currentBatchId && !progressDone(selectedBatch?.status);

  return (
    <div className="animate-fade-in max-w-6xl mx-auto space-y-5 pb-20">
      <div>
        <h1 className="font-display text-2xl text-gray-900">任务工作台</h1>
        <p className="text-sm text-gray-400 mt-1">
          上传、预分类、启动审查和智能体进度集中在这一屏完成。
        </p>
      </div>

      {!selectedBatch && (
        <>
          <section className="card p-5">
            <div
              onDrop={handleDrop}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              className={`border-2 border-dashed rounded-input p-8 text-center transition-all ${
                dragging ? 'border-primary bg-primary-soft' : 'border-air-border hover:border-air-border-accent'
              }`}
            >
              <input
                id="workbench-upload"
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
                className="hidden"
                onChange={(event) => {
                  if (event.target.files) addFiles(event.target.files);
                  event.currentTarget.value = '';
                }}
              />
              <label htmlFor="workbench-upload" className="cursor-pointer">
                <div className="text-base font-semibold text-gray-700">拖拽文件到这里</div>
                <div className="text-sm text-gray-400 mt-1">或点击选择文件，支持 Word / PDF / Excel / TXT</div>
                <div className="mt-1 text-xs text-amber-600">
                  PDF 稳定支持可复制文本；扫描件需开启 OCR；复杂图片型 PDF 暂不保证。
                </div>
              </label>
            </div>

            {files.length > 0 && (
              <div className="mt-5 space-y-3">
                <div className="text-sm font-semibold text-gray-900">已上传文件 ({files.length})</div>
                {files.map((item) => (
                  <div key={item.id} className="border border-air-border rounded-input p-3 bg-white">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-900 truncate">{item.file.name}</div>
                        <div className="text-xs text-gray-400">{formatSize(item.file.size)}</div>
                      </div>
                      <button type="button" onClick={() => removeFile(item.id)} className="btn-ghost text-xs py-1 px-2">
                        移除
                      </button>
                    </div>
                    {/* Auto-classification result */}
                    <div className="mt-2.5">
                      {item.classifying ? (
                        <div className="flex items-center gap-2 text-xs text-primary">
                          <span className="animate-spin inline-block w-3.5 h-3.5 border-2 border-primary/20 border-t-primary rounded-full" />
                          AI 智能分类中...
                        </div>
                      ) : item.classifyError ? (
                        <div className="text-xs text-amber-600">识别失败，已使用默认分类</div>
                      ) : item.autoClass ? (
                        <div className="space-y-2">
                          {/* Genre + Authority + Confidence */}
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold bg-blue-100 text-blue-700">
                              {item.autoClass.classification?.document_genre || item.autoClass.suggested_source_tag}
                            </span>
                            {item.autoClass.classification?.authority_level && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-emerald-50 text-emerald-700">
                                {item.autoClass.classification.authority_level}
                              </span>
                            )}
                            {item.autoClass.suggested_contract_types?.[0] && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-purple-50 text-purple-700">
                                {item.autoClass.suggested_contract_types[0]}
                              </span>
                            )}
                            {item.autoClass.suggested_our_party && item.autoClass.suggested_our_party !== '通用' && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-amber-50 text-amber-700">
                                {item.autoClass.suggested_our_party}
                              </span>
                            )}
                            <span className={`text-[11px] font-semibold ${item.autoClass.confidence >= 0.7 ? 'text-emerald-600' : item.autoClass.confidence >= 0.4 ? 'text-amber-600' : 'text-red-500'}`}>
                              {Math.round(item.autoClass.confidence * 100)}%
                            </span>
                          </div>
                          {/* Feature tags */}
                          {item.autoClass.classification?.feature_tags && (
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {item.autoClass.classification.feature_tags.is_redline && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-600 border border-red-200">红线</span>
                              )}
                              {item.autoClass.classification.feature_tags.is_case && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-50 text-purple-600 border border-purple-200">裁判文书</span>
                              )}
                              {item.autoClass.classification.feature_tags.is_template && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-50 text-sky-600 border border-sky-200">模板</span>
                              )}
                              {item.autoClass.classification.feature_tags.has_rules && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-teal-50 text-teal-600 border border-teal-200">含规则</span>
                              )}
                              {item.autoClass.classification?.industry_hints?.map((hint: string) => (
                                <span key={hint} className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-600">{hint}</span>
                              ))}
                            </div>
                          )}
                          {/* v1.2: 分类分歧需确认 — 高亮并给一键改选 */}
                          {item.autoClass.classification?.needs_confirmation && (
                            <div className="flex items-center gap-2 flex-wrap p-1.5 rounded-md bg-amber-50 border border-amber-200">
                              <span className="text-[11px] font-semibold text-amber-700">
                                分类需确认：AI 判为「{item.autoClass.classification.document_genre}」，
                                关键词预筛判为「{item.autoClass.classification.alternative_genre}」
                              </span>
                              <button
                                type="button"
                                onClick={() => {
                                  const alt = item.autoClass?.classification?.alternative_genre || '';
                                  const tag = GENRE_TO_SOURCE_TAG[alt];
                                  if (tag) updateFileMeta(item.id, { source_tag: tag });
                                }}
                                className="px-2 py-0.5 rounded text-[11px] font-medium bg-white text-amber-700 border border-amber-300 hover:bg-amber-100"
                              >
                                改用「{item.autoClass.classification.alternative_genre}」
                              </button>
                            </div>
                          )}
                          {/* Reasoning */}
                          {item.autoClass.classification?.reasoning && (
                            <div className="text-[11px] text-gray-400 truncate">
                              {item.autoClass.classification.reasoning}
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                    {/* Manual overrides (collapsed by default, expandable) */}
                    {/* Scanned file toggle */}
                    {item.autoClass && !item.autoClass.classification?.feature_tags && (
                      <label className="mt-2 flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!item.meta.is_scanned}
                          onChange={(event) => updateFileMeta(item.id, { is_scanned: event.target.checked })}
                          className="rounded border-gray-300 text-primary focus:ring-primary/30 w-3.5 h-3.5"
                        />
                        标记为扫描件
                      </label>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Batch-level domain selector — prominent position */}
          {files.length > 0 && (
            <section className="card p-5">
              <div className="text-sm font-semibold text-gray-900 mb-3">提取领域</div>
              <div className="text-xs text-gray-400 mb-3">选择本批次资料要提取的规则领域，系统会加载对应的行业词表和关注要点。</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {EXTRACTION_DOMAINS.map((domain) => (
                  <button
                    key={domain.value}
                    type="button"
                    onClick={() => setExtractionDomain(domain.value)}
                    className={`text-left px-3 py-2.5 rounded-lg border transition-all ${
                      extractionDomain === domain.value
                        ? 'border-primary bg-primary-soft ring-1 ring-primary/20'
                        : 'border-air-border hover:border-air-border-accent hover:bg-air-hover'
                    }`}
                  >
                    <div className={`text-sm font-medium ${extractionDomain === domain.value ? 'text-primary' : 'text-gray-700'}`}>
                      {domain.label}
                    </div>
                    <div className="text-[11px] text-gray-400 mt-0.5 truncate">{domain.desc}</div>
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Advanced config (collapsed) */}
          <section className="card overflow-hidden">
            <button
              type="button"
              onClick={() => setBatchConfigOpen((open) => !open)}
              className="w-full px-5 py-3 flex items-center justify-between text-left"
            >
              <div>
                <div className="text-sm font-semibold text-gray-900">高级配置</div>
                <div className="text-xs text-gray-400 mt-0.5">
                  模式: {TASK_MODES.find((mode) => mode.value === taskMode)?.label || '全量规则沉淀'} ｜ 颗粒度: {granularityLevel}（{GRANULARITY_LABELS[granularityLevel]?.label}） ｜ 法规深度: {config?.extraction.regulation_depth || '-'}
                </div>
              </div>
              <span className="text-sm text-primary">{batchConfigOpen ? '收起' : '展开'}</span>
            </button>
            {batchConfigOpen && config && (
              <div className="px-5 pb-4 border-t border-air-border grid grid-cols-1 md:grid-cols-3 gap-3">
                <label className="text-xs text-gray-500">
                  任务模式
                  <select
                    value={taskMode}
                    onChange={(event) => setTaskMode(event.target.value as CreateBatchMeta['task_mode'])}
                    className="select-field text-xs"
                  >
                    {TASK_MODES.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-gray-500 md:col-span-2">
                  抽取颗粒度：{granularityLevel} 档（{GRANULARITY_LABELS[granularityLevel]?.label}）
                  <input
                    type="range"
                    min={1}
                    max={5}
                    step={1}
                    value={granularityLevel}
                    onChange={(event) => setGranularityLevel(Number(event.target.value))}
                    className="w-full mt-1 accent-primary"
                  />
                  <span className="block text-[11px] text-gray-400 mt-0.5">
                    {GRANULARITY_LABELS[granularityLevel]?.desc}
                  </span>
                </label>
                <label className="text-xs text-gray-500">
                  法规深度
                  <select
                    value={config.extraction.regulation_depth}
                    onChange={(event) => updateExtraction('regulation_depth', event.target.value)}
                    className="select-field text-xs"
                  >
                    <option value="full">完整条款</option>
                    <option value="limited">摘要要点</option>
                  </select>
                </label>
                <label className="text-xs text-gray-500">
                  我方立场
                  <select
                    value={files[0]?.meta.our_party || '通用'}
                    onChange={(event) => files.forEach((f) => updateFileMeta(f.id, { our_party: event.target.value }))}
                    className="select-field text-xs"
                  >
                    {PARTY_OPTIONS.map((party) => (
                      <option key={party} value={party}>
                        {party}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-gray-500 md:col-span-2">
                  范围说明
                  <textarea
                    value={scopeDescription}
                    onChange={(event) => setScopeDescription(event.target.value)}
                    className="select-field min-h-[72px] resize-y text-xs"
                    placeholder="例如：只抽与本次采购模板付款、交付、验收、违约责任相关的规则"
                  />
                </label>
              </div>
            )}
          </section>

          <section className="card p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div className="text-sm text-gray-500">
              预计 Token: <span className="font-mono text-gray-900">{Math.round(estimatedTokens / 1000)}K</span> / {Math.round(tokensBudget / 1_000_000)}M
            </div>
            <button type="button" onClick={handleStart} disabled={!canStart} className="btn-primary text-sm">
              {submitting ? '启动中...' : '启动审查'}
            </button>
          </section>
        </>
      )}

      {submitError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-card text-sm text-red-600">
          {submitError}
        </div>
      )}

      {(running || progress) && (
        <>
          <section className="card p-5">
            <h2 className="text-base font-semibold text-gray-900 mb-3">分类阶段</h2>
            {files.length > 0 ? (
              <div className="space-y-2">
                {files.map((item) => (
                  <div key={item.id} className="text-sm text-gray-600">
                    {item.classifying ? '⟳' : '✓'} {item.file.name} →{' '}
                    {item.classifying
                      ? '识别中...'
                      : `${item.meta.contract_types[0] || item.meta.source_tag}（${item.autoClass ? Math.round(item.autoClass.confidence * 100) : 0}%）`}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-gray-500">任务已提交，正在读取后端进度。</div>
            )}
          </section>
          <PipelineProgress progress={progress} tokensBudget={tokensBudget} />
        </>
      )}
    </div>
  );
}
