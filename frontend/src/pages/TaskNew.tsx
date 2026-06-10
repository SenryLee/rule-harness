import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookmarkPlus,
  Check,
  FileText,
  Loader2,
  Save,
  Settings2,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import {
  createBatch,
  deleteTaskPreset,
  fetchProfile,
  fetchProfiles,
  fetchTaskPresets,
  previewClassify,
  saveTaskPreset,
} from '../api';
import type {
  CreateBatchMeta,
  PreviewClassifyResponse,
  Profile,
  TaskPreset,
  TaskPresetSettings,
} from '../api';

interface FileEntry {
  file: File;
  meta: CreateBatchMeta;
  preview?: PreviewClassifyResponse;
  classifying: boolean;
  classifyFailed?: boolean;
}

const STEPS = ['上传文件', '确认配置', '开始抽取'] as const;

/** 与后端 parsers._SOURCE_PRIORITY_MAP / 管道触发条件保持一致 */
const SOURCE_TAG_GROUPS: Array<{ group: string; tags: string[] }> = [
  { group: '法律与监管', tags: ['法规', '监管文件'] },
  { group: '企业规范', tags: ['公司红线', '谈判底线', '内部制度', '审批规则', '业务规范', '审查清单', '行业特殊'] },
  { group: '合同文本', tags: ['历史合同', '合同模板', '示范文本', '标准条款库'] },
  { group: '案例与争议', tags: ['案例', '争议材料'] },
];

const REDLINE_TAGS = new Set(['公司红线', '谈判底线']);
const CASE_TAGS = new Set(['案例', '争议材料']);
const LAW_TAGS = new Set(['法规', '监管文件']);

/** 镜像后端 classifier._map_to_source_tag，用于「分歧二选一」 */
const GENRE_TO_TAG: Record<string, string> = {
  法律法规: '法规',
  监管与司法文件: '监管文件',
  裁判文书: '案例',
  合同文本: '历史合同',
  企业内部文件: '内部制度',
  已有规则库: '标准条款库',
  专业参考资料: '业务规范',
};

function pipelineHint(tag: string): string | null {
  if (REDLINE_TAGS.has(tag)) return '将启用 P4 谈判红线阶梯抽取';
  if (CASE_TAGS.has(tag)) return '将启用 P5 案例反推抽取';
  if (LAW_TAGS.has(tag)) return '将按法规逐条深抽（必抽清单模式）';
  return null;
}

/** 标签联动：红线/案例标签自动点亮对应管道开关（后端为严格 AND） */
function metaForTag(meta: CreateBatchMeta, tag: string): CreateBatchMeta {
  return {
    ...meta,
    source_tag: tag,
    is_redline: REDLINE_TAGS.has(tag),
    is_case: CASE_TAGS.has(tag),
  };
}

const GRANULARITY_LABELS: Record<number, string> = {
  1: '粗 · 只抓核心义务',
  2: '较粗 · 主要条款',
  3: '均衡 · 常规审查',
  4: '细 · 逐条覆盖（推荐）',
  5: '极细 · 原子级拆分',
};

interface TaskConfig {
  granularity_level: number;
  task_mode: 'full_library' | 'template_focused' | 'template_strategy';
  regulation_depth: 'full' | 'limited';
  consistency_sampling: boolean;
  our_party: string;
  scope_description: string;
  industry_preset: string | null;
  industry_vocabulary: string;
  industry_focus_points: string;
}

const DEFAULT_TASK_CONFIG: TaskConfig = {
  granularity_level: 4,
  task_mode: 'full_library',
  regulation_depth: 'full',
  consistency_sampling: false,
  our_party: '',
  scope_description: '',
  industry_preset: null,
  industry_vocabulary: '',
  industry_focus_points: '',
};

export default function TaskNew() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [taskConfig, setTaskConfig] = useState<TaskConfig>(DEFAULT_TASK_CONFIG);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [presets, setPresets] = useState<TaskPreset[]>([]);
  const [presetName, setPresetName] = useState('');
  const [presetSaving, setPresetSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    fetchProfiles().then(setProfiles).catch(() => {});
    fetchTaskPresets().then(setPresets).catch(() => {});
  }, []);

  const classifyingCount = files.filter((f) => f.classifying).length;
  const allClassified = files.length > 0 && classifyingCount === 0;

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    addFiles(Array.from(e.dataTransfer.files));
  }, []);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
    e.target.value = '';
  };

  const addFiles = (newFiles: File[]) => {
    const entries: FileEntry[] = newFiles.map((file) => ({
      file,
      meta: { source_tag: '历史合同', contract_types: [] },
      classifying: true,
    }));
    setFiles((prev) => [...prev, ...entries]);

    entries.forEach((entry) => {
      previewClassify(entry.file)
        .then((result) => {
          setFiles((prev) =>
            prev.map((f) => {
              if (f.file !== entry.file) return f;
              const tag = result.suggested_source_tag || f.meta.source_tag;
              return {
                ...f,
                preview: result,
                classifying: false,
                meta: {
                  ...metaForTag(f.meta, tag),
                  contract_types: result.suggested_contract_types || [],
                },
              };
            }),
          );
        })
        .catch(() => {
          setFiles((prev) =>
            prev.map((f) =>
              f.file === entry.file ? { ...f, classifying: false, classifyFailed: true } : f,
            ),
          );
        });
    });
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const setFileTag = (idx: number, tag: string) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === idx ? { ...f, meta: metaForTag(f.meta, tag) } : f)),
    );
  };

  const applyPreset = (preset: TaskPreset) => {
    const s: TaskPresetSettings = preset.settings || {};
    setTaskConfig((prev) => ({
      ...prev,
      granularity_level: s.granularity_level ?? prev.granularity_level,
      task_mode: s.task_mode ?? prev.task_mode,
      regulation_depth: s.regulation_depth ?? prev.regulation_depth,
      consistency_sampling: s.consistency_sampling ?? prev.consistency_sampling,
      our_party: s.our_party ?? prev.our_party,
      scope_description: s.scope_description ?? prev.scope_description,
      industry_preset: s.industry_preset ?? prev.industry_preset,
      industry_vocabulary: s.industry_vocabulary ?? prev.industry_vocabulary,
      industry_focus_points: s.industry_focus_points ?? prev.industry_focus_points,
    }));
  };

  const handleSavePreset = async () => {
    const name = presetName.trim();
    if (!name || presetSaving) return;
    setPresetSaving(true);
    try {
      const settings: TaskPresetSettings = {
        granularity_level: taskConfig.granularity_level,
        task_mode: taskConfig.task_mode,
        regulation_depth: taskConfig.regulation_depth,
        consistency_sampling: taskConfig.consistency_sampling,
        our_party: taskConfig.our_party || undefined,
        scope_description: taskConfig.scope_description || undefined,
        industry_preset: taskConfig.industry_preset,
        industry_vocabulary: taskConfig.industry_vocabulary || undefined,
        industry_focus_points: taskConfig.industry_focus_points || undefined,
      };
      await saveTaskPreset(name, settings);
      setPresets(await fetchTaskPresets());
      setPresetName('');
    } catch {
      // 保存失败静默；列表不变即可感知
    } finally {
      setPresetSaving(false);
    }
  };

  const handleDeletePreset = async (name: string) => {
    try {
      await deleteTaskPreset(name);
      setPresets((prev) => prev.filter((p) => p.name !== name));
    } catch {
      // ignore
    }
  };

  const handleSelectIndustry = async (name: string) => {
    if (!name) {
      setTaskConfig((prev) => ({
        ...prev,
        industry_preset: null,
        industry_vocabulary: '',
        industry_focus_points: '',
      }));
      return;
    }
    setTaskConfig((prev) => ({ ...prev, industry_preset: name }));
    try {
      const profile = await fetchProfile(name);
      const vocab = Array.isArray(profile.vocabulary)
        ? profile.vocabulary.join('\n')
        : profile.vocabulary || '';
      setTaskConfig((prev) => ({
        ...prev,
        industry_vocabulary: vocab,
        industry_focus_points: profile.focus_points || '',
      }));
    } catch {
      // profile 加载失败时仅记录选择
    }
  };

  const handleSubmit = async () => {
    setSubmitError(null);
    try {
      const metas = files.map((f, idx) => {
        const meta: CreateBatchMeta = {
          ...f.meta,
          our_party: taskConfig.our_party || undefined,
        };
        if (idx === 0) {
          meta.granularity_level = taskConfig.granularity_level;
          meta.task_mode = taskConfig.task_mode;
          meta.scope_description = taskConfig.scope_description || undefined;
          meta.extraction_overrides = {
            granularity_level: taskConfig.granularity_level,
            regulation_depth: taskConfig.regulation_depth,
            consistency_sampling: taskConfig.consistency_sampling,
            industry_vocabulary: taskConfig.industry_vocabulary || undefined,
            industry_focus_points: taskConfig.industry_focus_points || undefined,
          };
        }
        return meta;
      });
      const result = await createBatch(files.map((f) => f.file), metas);
      navigate(`/tasks/${result.batch_id}`);
    } catch (error: unknown) {
      setStep(1);
      setSubmitError(error instanceof Error ? error.message : '创建任务失败，请重试');
    }
  };

  return (
    <div className="animate-page-in space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">新建任务</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">上传法律文件，启动规则抽取</p>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold transition-all ${
                i <= step
                  ? 'bg-[var(--color-accent)] text-white shadow-[0_2px_8px_var(--color-accent-soft)]'
                  : 'glass-chip text-[var(--text-muted)]'
              }`}
            >
              {i + 1}
            </div>
            <span
              className={`text-sm ${
                i <= step ? 'font-medium text-[var(--text-primary)]' : 'text-[var(--text-muted)]'
              }`}
            >
              {label}
            </span>
            {i < STEPS.length - 1 && <div className="mx-2 h-px w-8 bg-[var(--border)]" />}
          </div>
        ))}
      </div>

      {/* Step 1: Upload */}
      {step === 0 && (
        <div className="space-y-4">
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            className="card flex cursor-pointer flex-col items-center justify-center border-2 border-dashed border-[var(--border)] px-6 py-16 transition-colors hover:border-[var(--color-accent)]"
            onClick={() => document.getElementById('file-input')?.click()}
          >
            <Upload size={32} className="mb-3 text-[var(--text-muted)]" />
            <p className="text-sm font-medium">拖拽文件到此处，或点击选择</p>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              支持 PDF、Word、Excel、CSV、TXT 格式
            </p>
            <input
              id="file-input"
              type="file"
              multiple
              accept=".pdf,.docx,.doc,.txt,.md,.xlsx,.xls,.csv,.tsv"
              className="hidden"
              onChange={handleFileInput}
            />
          </div>

          {files.length > 0 && (
            <div className="space-y-2">
              {files.map((entry, idx) => (
                <div key={idx} className="card flex items-center gap-3 px-4 py-3">
                  <FileText size={18} className="flex-shrink-0 text-[var(--text-muted)]" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{entry.file.name}</p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
                      <span>{(entry.file.size / 1024).toFixed(0)} KB</span>
                      {entry.classifying && (
                        <span className="inline-flex items-center gap-1 text-[var(--color-accent)]">
                          <Loader2 size={12} className="animate-spin" /> 智能分类中…
                        </span>
                      )}
                      {!entry.classifying && entry.preview && (
                        <>
                          <span className="glass-chip px-2 py-0.5 font-medium text-[var(--text-secondary)]">
                            {entry.meta.source_tag}
                          </span>
                          {entry.preview.classification?.document_genre && (
                            <span>{entry.preview.classification.document_genre}</span>
                          )}
                          <span>置信 {Math.round((entry.preview.confidence ?? 0) * 100)}%</span>
                          {entry.preview.classification?.needs_confirmation && (
                            <span className="inline-flex items-center gap-1 text-[var(--color-amber)]">
                              <AlertTriangle size={12} /> 需确认
                            </span>
                          )}
                        </>
                      )}
                      {!entry.classifying && entry.classifyFailed && (
                        <span className="text-[var(--color-amber)]">自动分类失败，请下一步手动选择</span>
                      )}
                    </div>
                  </div>
                  {!entry.classifying && !entry.classifyFailed && entry.preview && (
                    <Check size={16} className="flex-shrink-0 text-[var(--color-green)]" />
                  )}
                  <button
                    onClick={() => removeFile(idx)}
                    className="text-[var(--text-muted)] transition-colors hover:text-[var(--color-red)]"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-end gap-3">
            {classifyingCount > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <Loader2 size={13} className="animate-spin" />
                正在分类 {files.length - classifyingCount}/{files.length}，完成后才可进入下一步
              </span>
            )}
            <button
              className="btn-primary"
              disabled={!allClassified}
              onClick={() => setStep(1)}
            >
              下一步 <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Configure */}
      {step === 1 && (
        <div className="space-y-4">
          {submitError && (
            <div className="card border-[var(--color-red)] px-4 py-3 text-sm text-[var(--color-red)]">
              {submitError}
            </div>
          )}

          {/* 文件分类确认 */}
          <div className="card space-y-1 p-5">
            <h3 className="mb-3 text-sm font-semibold">文件分类确认</h3>
            {files.map((entry, idx) => {
              const clf = entry.preview?.classification;
              const hint = pipelineHint(entry.meta.source_tag);
              const altTag = clf?.alternative_genre ? GENRE_TO_TAG[clf.alternative_genre] : undefined;
              return (
                <div
                  key={idx}
                  className="border-b border-[var(--border-light)] py-3 last:border-0"
                >
                  <div className="flex items-center gap-4">
                    <p className="flex-1 truncate text-sm">{entry.file.name}</p>
                    <select
                      className="input-field w-auto min-w-[150px]"
                      value={entry.meta.source_tag}
                      onChange={(e) => setFileTag(idx, e.target.value)}
                    >
                      {SOURCE_TAG_GROUPS.map(({ group, tags }) => (
                        <optgroup key={group} label={group}>
                          {tags.map((tag) => (
                            <option key={tag} value={tag}>
                              {tag}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                    {entry.preview && (
                      <span className="w-20 text-right text-xs text-[var(--text-muted)]">
                        置信 {Math.round((entry.preview.confidence ?? 0) * 100)}%
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 pl-0.5">
                    {clf?.document_genre && (
                      <span className="text-xs text-[var(--text-muted)]">
                        {clf.document_genre} · {clf.authority_level}
                        {clf.reasoning ? ` · ${clf.reasoning}` : ''}
                      </span>
                    )}
                    {hint && <span className="badge-info">{hint}</span>}
                  </div>
                  {clf?.needs_confirmation && altTag && altTag !== entry.meta.source_tag && (
                    <div className="mt-2 flex items-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-amber-soft)] px-3 py-2">
                      <AlertTriangle size={14} className="flex-shrink-0 text-[var(--color-amber)]" />
                      <span className="text-xs text-[var(--text-secondary)]">
                        分类有分歧：也可能是「{clf.alternative_genre}」
                      </span>
                      <button
                        className="ml-auto text-xs font-semibold text-[var(--color-accent)] hover:underline"
                        onClick={() => setFileTag(idx, altTag)}
                      >
                        改用 {altTag}
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* 抽取配置 */}
          <div className="card space-y-5 p-5">
            <div className="flex items-center justify-between">
              <h3 className="inline-flex items-center gap-2 text-sm font-semibold">
                <Settings2 size={15} /> 抽取配置
              </h3>
              {/* 预设 */}
              <div className="flex items-center gap-2">
                {presets.length > 0 && (
                  <select
                    className="input-field w-auto min-w-[130px] py-1.5 text-xs"
                    value=""
                    onChange={(e) => {
                      const preset = presets.find((p) => p.name === e.target.value);
                      if (preset) applyPreset(preset);
                    }}
                  >
                    <option value="" disabled>
                      载入预设…
                    </option>
                    {presets.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              {/* 颗粒度 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  抽取颗粒度 · {GRANULARITY_LABELS[taskConfig.granularity_level]}
                </label>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={taskConfig.granularity_level}
                  onChange={(e) =>
                    setTaskConfig((prev) => ({
                      ...prev,
                      granularity_level: Number(e.target.value),
                    }))
                  }
                  className="w-full accent-[var(--color-accent)]"
                />
                <div className="flex justify-between text-[10px] text-[var(--text-muted)]">
                  <span>粗</span>
                  <span>极细</span>
                </div>
              </div>

              {/* 任务模式 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  任务模式
                </label>
                <select
                  className="input-field"
                  value={taskConfig.task_mode}
                  onChange={(e) =>
                    setTaskConfig((prev) => ({
                      ...prev,
                      task_mode: e.target.value as TaskConfig['task_mode'],
                    }))
                  }
                >
                  <option value="full_library">全量规则沉淀</option>
                  <option value="template_focused">围绕模板抽取</option>
                  <option value="template_strategy">对我方有利模板生成</option>
                </select>
              </div>

              {/* 行业 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  行业画像（注入行业词表与关注要点）
                </label>
                <select
                  className="input-field"
                  value={taskConfig.industry_preset ?? ''}
                  onChange={(e) => handleSelectIndustry(e.target.value)}
                >
                  <option value="">通用（不指定）</option>
                  {profiles.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.label || p.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* 我方立场 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  我方立场（可选）
                </label>
                <input
                  className="input-field"
                  placeholder="如：发包人 / 甲方 / 买方"
                  value={taskConfig.our_party}
                  onChange={(e) =>
                    setTaskConfig((prev) => ({ ...prev, our_party: e.target.value }))
                  }
                />
              </div>
            </div>

            {taskConfig.task_mode !== 'full_library' && (
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  抽取范围说明（聚焦模式下用于过滤无关规则）
                </label>
                <textarea
                  className="input-field min-h-[64px]"
                  placeholder="如：只关注付款、违约、知识产权相关条款"
                  value={taskConfig.scope_description}
                  onChange={(e) =>
                    setTaskConfig((prev) => ({ ...prev, scope_description: e.target.value }))
                  }
                />
              </div>
            )}

            {/* 高级选项 */}
            <button
              className="text-xs font-medium text-[var(--color-accent)] hover:underline"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? '收起高级选项' : '展开高级选项'}
            </button>
            {showAdvanced && (
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                    法规抽取深度
                  </label>
                  <select
                    className="input-field"
                    value={taskConfig.regulation_depth}
                    onChange={(e) =>
                      setTaskConfig((prev) => ({
                        ...prev,
                        regulation_depth: e.target.value as 'full' | 'limited',
                      }))
                    }
                  >
                    <option value="full">全文逐条（推荐）</option>
                    <option value="limited">仅重点章节</option>
                  </select>
                </div>
                <div className="flex items-end pb-2">
                  <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-medium text-[var(--text-secondary)]">
                    <input
                      type="checkbox"
                      className="accent-[var(--color-accent)]"
                      checked={taskConfig.consistency_sampling}
                      onChange={(e) =>
                        setTaskConfig((prev) => ({
                          ...prev,
                          consistency_sampling: e.target.checked,
                        }))
                      }
                    />
                    一致性采样（双跑校验，更准但更慢）
                  </label>
                </div>
                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                    行业词表（每行一个，覆盖全局配置）
                  </label>
                  <textarea
                    className="input-field min-h-[64px] font-mono text-xs"
                    value={taskConfig.industry_vocabulary}
                    onChange={(e) =>
                      setTaskConfig((prev) => ({
                        ...prev,
                        industry_vocabulary: e.target.value,
                      }))
                    }
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                    行业关注要点
                  </label>
                  <textarea
                    className="input-field min-h-[64px]"
                    value={taskConfig.industry_focus_points}
                    onChange={(e) =>
                      setTaskConfig((prev) => ({
                        ...prev,
                        industry_focus_points: e.target.value,
                      }))
                    }
                  />
                </div>
              </div>
            )}

            {/* 保存预设 */}
            <div className="flex items-center gap-2 border-t border-[var(--border-light)] pt-4">
              <BookmarkPlus size={15} className="text-[var(--text-muted)]" />
              <input
                className="input-field w-48 py-1.5 text-xs"
                placeholder="预设名称，如：建工全量·细"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
              />
              <button
                className="btn-secondary px-3 py-1.5 text-xs"
                disabled={!presetName.trim() || presetSaving}
                onClick={handleSavePreset}
              >
                <Save size={13} /> 保存为预设
              </button>
              {presets.length > 0 && (
                <div className="ml-auto flex flex-wrap items-center gap-1.5">
                  {presets.map((p) => (
                    <span
                      key={p.name}
                      className="glass-chip inline-flex items-center gap-1 px-2 py-0.5 text-[11px] text-[var(--text-secondary)]"
                    >
                      {p.name}
                      <button
                        className="text-[var(--text-muted)] hover:text-[var(--color-red)]"
                        onClick={() => handleDeletePreset(p.name)}
                        title="删除预设"
                      >
                        <Trash2 size={11} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex justify-between">
            <button className="btn-secondary" onClick={() => setStep(0)}>
              <ArrowLeft size={16} /> 上一步
            </button>
            <button
              className="btn-primary"
              onClick={() => {
                setStep(2);
                handleSubmit();
              }}
            >
              开始抽取 <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Submitting */}
      {step === 2 && (
        <div className="card px-6 py-16 text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-[var(--color-accent)] border-t-transparent" />
          <p className="mt-4 text-sm text-[var(--text-muted)]">正在创建任务并启动抽取...</p>
        </div>
      )}
    </div>
  );
}
