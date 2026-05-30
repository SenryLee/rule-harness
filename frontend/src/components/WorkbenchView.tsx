import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createBatch,
  fetchBatch,
  fetchBatchProgress,
  fetchConfig,
  previewClassify,
  updateConfig,
} from '../api';
import type { Batch, BatchProgress, Config, CreateBatchMeta, PreviewClassifyResponse } from '../api';
import PipelineProgress from './PipelineProgress';

const SOURCE_CATEGORIES = [
  '法规',
  '公司红线',
  '内部制度',
  '标准条款库',
  '合同模板',
  '历史合同',
  '业务规范',
  '案例',
  '行业特殊',
  '审查清单',
];

const CONTRACT_TYPES = [
  '建工·总包',
  '建工·勘察设计',
  '房地产',
  '金融',
  '医药',
  'IT',
  '制造',
  '能源·电力',
  '汽车',
  '通用商事',
  '采购',
  '销售',
  '服务',
  '保密',
  '技术',
  '许可',
  '租赁',
  '劳动',
];

const PARTY_OPTIONS = ['通用', '甲方', '乙方', '发包人', '承包人', '买方', '卖方', '出租人', '承租人'];

const TASK_MODES = [
  { value: 'full_library', label: '全量规则沉淀' },
  { value: 'template_focused', label: '围绕模板抽取' },
  { value: 'template_strategy', label: '我方模板策略' },
] as const;

interface UploadedFile {
  id: string;
  file: File;
  meta: CreateBatchMeta;
  classifying: boolean;
  classifyError?: string | null;
  autoClass?: PreviewClassifyResponse | null;
}

interface WorkbenchViewProps {
  selectedBatch: Batch | null;
  onBatchUpdated: (batch: Batch) => void;
  onRefresh: () => void;
}

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

export default function WorkbenchView({ selectedBatch, onBatchUpdated, onRefresh }: WorkbenchViewProps) {
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
  const [scopeDescription, setScopeDescription] = useState('');
  const idCounter = useRef(0);

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
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

    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchBatchProgress(batchId);
        if (cancelled) return;
        setProgress(next);
        if (progressDone(next.status)) {
          const detail = await fetchBatch(batchId);
          if (!cancelled) {
            onBatchUpdated(detail);
            onRefresh();
          }
        }
      } catch {
        // Keep the last visible state; transient polling failures are common during startup.
      }
    };

    poll();
    const timer = window.setInterval(poll, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [currentBatchId, onBatchUpdated, onRefresh, selectedBatch?.batch_id, selectedBatch?.status]);

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
      if (config && configDirty) {
        await updateConfig(config);
      }
      const meta = files.map((item) => ({
        ...item.meta,
        contract_types: item.meta.contract_types || [],
        is_redline: item.meta.source_tag === '公司红线',
        is_case: item.meta.source_tag === '案例',
        task_mode: taskMode,
        scope_description: scopeDescription.trim(),
      }));
      const created = await createBatch(files.map((item) => item.file), meta);
      setCurrentBatchId(created.batch_id);
      const detail = await fetchBatch(created.batch_id);
      onBatchUpdated(detail);
      onRefresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '启动失败');
    } finally {
      setSubmitting(false);
    }
  }, [canStart, config, configDirty, files, onBatchUpdated, onRefresh, scopeDescription, taskMode]);

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
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mt-3">
                      <label className="text-xs text-gray-500">
                        来源类别
                        <select
                          value={item.meta.source_tag}
                          onChange={(event) => updateFileMeta(item.id, { source_tag: event.target.value })}
                          className="select-field text-xs"
                        >
                          {SOURCE_CATEGORIES.map((source) => (
                            <option key={source} value={source}>
                              {source}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs text-gray-500">
                        合同类型
                        <select
                          value={item.meta.contract_types[0] || ''}
                          onChange={(event) =>
                            updateFileMeta(item.id, {
                              contract_types: event.target.value ? [event.target.value] : [],
                            })
                          }
                          className="select-field text-xs"
                        >
                          <option value="">通用</option>
                          {CONTRACT_TYPES.map((contractType) => (
                            <option key={contractType} value={contractType}>
                              {contractType}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs text-gray-500">
                        我方立场
                        <select
                          value={item.meta.our_party || '通用'}
                          onChange={(event) => updateFileMeta(item.id, { our_party: event.target.value })}
                          className="select-field text-xs"
                        >
                          {PARTY_OPTIONS.map((party) => (
                            <option key={party} value={party}>
                              {party}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="flex items-end gap-2 text-xs text-gray-600 pb-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!item.meta.is_scanned}
                          onChange={(event) => updateFileMeta(item.id, { is_scanned: event.target.checked })}
                          className="rounded border-gray-300 text-primary focus:ring-primary/30"
                        />
                        是否扫描件
                      </label>
                    </div>
                    <div className="mt-2 text-xs">
                      {item.classifying ? (
                        <span className="text-primary">识别中...</span>
                      ) : item.classifyError ? (
                        <span className="text-amber-600">识别失败，请手动配置</span>
                      ) : item.autoClass ? (
                        <span className={(item.autoClass.auto_apply_source || item.autoClass.auto_apply_contract) ? 'text-emerald-600' : 'text-amber-600'}>
                          {(item.autoClass.auto_apply_source || item.autoClass.auto_apply_contract) ? '自动识别' : '建议'}:{' '}
                          {[
                            item.autoClass.suggested_source_tag,
                            ...(item.autoClass.suggested_contract_types || []),
                          ].filter(Boolean).join('、') || item.meta.source_tag}
                          （置信度 {Math.round(item.autoClass.confidence * 100)}%）
                          {!(item.autoClass.auto_apply_source || item.autoClass.auto_apply_contract) ? '，未自动应用' : ''}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card overflow-hidden">
            <button
              type="button"
              onClick={() => setBatchConfigOpen((open) => !open)}
              className="w-full px-5 py-3 flex items-center justify-between text-left"
            >
              <div>
                <div className="text-sm font-semibold text-gray-900">批次配置</div>
                <div className="text-xs text-gray-400 mt-0.5">
                  模式: {TASK_MODES.find((mode) => mode.value === taskMode)?.label || '全量规则沉淀'} ｜ 行业预设: {config?.extraction.industry_preset || '通用'} ｜ 颗粒度: {config?.extraction.granularity || '-'} ｜ 法规深度: {config?.extraction.regulation_depth || '-'}
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
                <label className="text-xs text-gray-500">
                  行业预设
                  <select
                    value={config.extraction.industry_preset || ''}
                    onChange={(event) => updateExtraction('industry_preset', event.target.value || null)}
                    className="select-field text-xs"
                  >
                    <option value="">通用</option>
                    {CONTRACT_TYPES.slice(0, 10).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-gray-500">
                  抽取颗粒度
                  <select
                    value={config.extraction.granularity}
                    onChange={(event) => updateExtraction('granularity', event.target.value)}
                    className="select-field text-xs"
                  >
                    <option value="fine">精细</option>
                    <option value="balanced">平衡</option>
                  </select>
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
                <label className="text-xs text-gray-500 md:col-span-3">
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
