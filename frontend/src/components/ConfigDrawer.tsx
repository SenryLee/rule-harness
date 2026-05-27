import { useState, useEffect, useCallback } from 'react';
import {
  fetchConfig,
  updateConfig,
  fetchProfiles,
  fetchProfile,
  saveProfile,
  deleteProfile,
} from '../api';
import type {
  Config,
  ConfigExtraction,
  PriorityKey,
  ConfidenceWeights,
  ConfigConcurrency,
  ConfigOcr,
  ConfigBudget,
  ConfigStorage,
  Profile,
} from '../api';

/* ──────────────── Types ──────────────── */

interface ConfigDrawerProps {
  onClose: () => void;
  onSaved: () => void;
}

/* ──────────────── Default Config ──────────────── */

const DEFAULT_CONFIG: Config = {
  models: {
    primary: {
      provider: 'openai',
      api_key: '',
      base_url: '',
      model: 'gpt-4o',
      rpm_limit: 60,
      tpm_limit: 100000,
    },
    fallback: null,
  },
  extraction: {
    granularity: 'balanced',
    regulation_depth: 'full',
    consistency_sampling: false,
    industry_preset: '',
    industry_vocabulary: '',
    industry_focus_points: '',
    redline_keywords: [],
  },
  priorities: {
    weights: {
      '法规': 1,
      '公司红线': 2,
      '内部制度': 3,
      '标准条款库': 4,
      '历史合同': 5,
    },
  },
  confidence: {
    threshold_review: 0.7,
    weights: {
      self: 0.25,
      consistency: 0.25,
      struct: 0.15,
      conflict: 0.05,
      fidelity: 0.30,
    },
  },
  concurrency: {
    files: 3,
    blocks: 5,
  },
  ocr: {
    enabled: false,
    engine: 'paddleocr',
    language: 'ch+en',
  },
  budget: {
    max_tokens_per_batch: 500000,
    pause_on_overrun: false,
  },
  storage: {
    db_path: './data/rules.db',
    exports_dir: './exports',
  },
};

/* ──────────────── Sub-components ──────────────── */

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      className={`card mb-4 transition-colors ${
        open ? 'border-l-[3px] border-l-primary' : ''
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 text-left group"
      >
        <h3 className="text-base font-semibold text-gray-900 group-hover:text-primary transition-colors">
          {title}
        </h3>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform group-hover:text-primary ${
            open ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ease-out ${
          open ? 'max-h-[3000px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-5 pb-4">{children}</div>
      </div>
    </div>
  );
}

function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-sm font-medium text-gray-600 mb-1.5"
    >
      {children}
    </label>
  );
}

/**
 * v1.1: 红线关键词复选选择器。
 *
 * 设计理由：实测中"输入回车追加"对法务用户太不直观。改为内置词表勾选 + 自定义
 * 追加的组合形态：
 *   - 内置词表分 4 组（强义务 / 责任与赔偿 / 争议解决 / 合规高敏），覆盖 80% 场景；
 *   - 自定义 chip 区显示已添加的非内置词；
 *   - 顶部"全选 / 全不选"快捷键。
 */
const REDLINE_PRESETS: { group: string; words: string[] }[] = [
  {
    group: '强义务 / 禁止',
    words: ['不得', '禁止', '必须', '应当', '严禁', '红线', '重大', '无效'],
  },
  {
    group: '责任与赔偿',
    words: [
      '无限责任', '最高限额', '赔偿上限', '违约金',
      '损害赔偿', '间接损失', '可得利益', '惩罚性赔偿',
    ],
  },
  {
    group: '争议解决与法律适用',
    words: ['仲裁', '管辖', '法律适用', '法律选择', '不可转让'],
  },
  {
    group: '合规高敏',
    words: [
      '反贿赂', '反洗钱', '数据出境', '个人信息', '制裁',
      '独占许可', '排他许可', '永久许可', '全球范围',
    ],
  },
];

const BUILTIN_PROFILE_NAMES = new Set([
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
  '建筑',
  '建工勘察设计',
  '能源电力',
  'test',
]);

function RedlineKeywordsPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [customInput, setCustomInput] = useState('');
  const presetSet = new Set(REDLINE_PRESETS.flatMap((g) => g.words));
  const customWords = selected.filter((w) => !presetSet.has(w));

  const toggleWord = (word: string) => {
    if (selected.includes(word)) {
      onChange(selected.filter((w) => w !== word));
    } else {
      onChange([...selected, word]);
    }
  };

  const allPresetSelected = REDLINE_PRESETS.every((g) =>
    g.words.every((w) => selected.includes(w)),
  );

  const toggleAllPresets = () => {
    if (allPresetSelected) {
      onChange(selected.filter((w) => !presetSet.has(w)));
    } else {
      const allPreset = REDLINE_PRESETS.flatMap((g) => g.words);
      const merged = Array.from(new Set([...selected, ...allPreset]));
      onChange(merged);
    }
  };

  const addCustom = () => {
    const trimmed = customInput.trim();
    if (trimmed && !selected.includes(trimmed)) {
      onChange([...selected, trimmed]);
      setCustomInput('');
    }
  };

  return (
    <div className="space-y-3">
      {/* 全选 / 反选 */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">
          已选 <span className="font-semibold text-primary">{selected.length}</span> 项
        </span>
        <button
          type="button"
          onClick={toggleAllPresets}
          className="text-primary hover:underline"
        >
          {allPresetSelected ? '清空预设' : '全选预设'}
        </button>
      </div>

      {/* 预设分组 */}
      <div className="space-y-3">
        {REDLINE_PRESETS.map((group) => (
          <div key={group.group}>
            <div className="text-xs font-medium text-gray-500 mb-1.5">
              {group.group}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {group.words.map((word) => {
                const checked = selected.includes(word);
                return (
                  <button
                    key={word}
                    type="button"
                    onClick={() => toggleWord(word)}
                    className={
                      checked
                        ? 'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-primary text-white border border-primary'
                        : 'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-gray-700 border border-air-border hover:border-primary hover:text-primary transition-colors'
                    }
                  >
                    {checked && (
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {word}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 自定义追加 */}
      <div>
        <div className="text-xs font-medium text-gray-500 mb-1.5">
          自定义关键词
        </div>
        {customWords.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {customWords.map((word) => (
              <span
                key={word}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200"
              >
                {word}
                <button
                  type="button"
                  onClick={() => onChange(selected.filter((w) => w !== word))}
                  className="text-amber-500 hover:text-amber-700"
                >
                  &times;
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={customInput}
            onChange={(e) => setCustomInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="输入自定义词，回车追加"
            className="input-field flex-1 text-sm"
          />
          <button
            type="button"
            onClick={addCustom}
            disabled={!customInput.trim()}
            className="btn-secondary text-sm disabled:opacity-40"
          >
            添加
          </button>
        </div>
      </div>
    </div>
  );
}

// 旧的 TagInput 已被 RedlineKeywordsPicker 取代；如未来需要自由输入 tag，可在此重建。

/* ──────────────── Main Component ──────────────── */

export default function ConfigDrawer({ onClose, onSaved }: ConfigDrawerProps) {
  const [config, setConfig] = useState<Config>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedProfileName, setSelectedProfileName] = useState('');

  /* ─── Load config ─── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchConfig()
      .then((cfg) => {
        if (!cancelled) {
          if (cfg.models.fallback && !cfg.models.fallback.provider) {
            cfg = { ...cfg, models: { ...cfg.models, fallback: null } };
          }
          setConfig(cfg);
          setSelectedProfileName(cfg.extraction.industry_preset || '');
        }
      })
      .catch((err) => {
        if (!cancelled) setMessage({ type: 'error', text: err.message });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    fetchProfiles()
      .then((res) => {
        if (!cancelled) setProfiles(Array.isArray(res) ? res : []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  /* ─── Save ─── */
  const handleSave = useCallback(async () => {
    setSaving(true);
    setMessage(null);
    try {
      await updateConfig(config);
      setMessage({ type: 'success', text: '配置已保存' });
      onSaved();
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '保存失败' });
    } finally {
      setSaving(false);
    }
  }, [config, onSaved]);

  /* ─── Profile management ─── */
  const handleExportProfile = useCallback(
    async (profileName: string) => {
      try {
        await saveProfile(profileName, config);
        setMessage({ type: 'success', text: `配置已导出为方案: ${profileName}` });
        const res = await fetchProfiles();
        setProfiles(Array.isArray(res) ? res : []);
        setTimeout(() => setMessage(null), 3000);
      } catch (err) {
        setMessage({ type: 'error', text: err instanceof Error ? err.message : '导出失败' });
      }
    },
    [config],
  );

  const handleImportProfile = useCallback(async (name: string) => {
    if (!name) return;
    setMessage(null);
    try {
      const profile = await fetchProfile(name);
      // FIX #5 + #7：profile 是行业预设（只含 vocabulary / focus_points 等少量字段），
      // 不能直接覆盖 config（会让 config.models / config.confidence 等关键字段变 undefined
      // → 渲染时白屏）。正确做法：把预设内容 merge 进 config.extraction 对应字段。
      setConfig((prev) => ({
        ...prev,
        extraction: {
          ...prev.extraction,
          industry_preset: name,
          industry_vocabulary: Array.isArray(profile.vocabulary)
            ? profile.vocabulary.join('\n')
            : (profile.vocabulary || ''),
          industry_focus_points: profile.focus_points || '',
        },
      }));
      setSelectedProfileName(name);
      setMessage({ type: 'success', text: `已应用方案: ${name}（行业词表/关注要点已注入）` });
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '导入失败' });
    }
  }, []);

  const handleDeleteProfile = useCallback(async (name: string) => {
    if (!name) return;
    const profile = profiles.find((p) => p.name === name);
    const label = profile?.label || profile?.name || name;
    if (BUILTIN_PROFILE_NAMES.has(name) || BUILTIN_PROFILE_NAMES.has(label)) {
      setMessage({ type: 'error', text: '内置方案不可删除' });
      return;
    }
    if (!confirm(`确认删除方案: ${label}？`)) return;
    try {
      await deleteProfile(name);
      setMessage({ type: 'success', text: `已删除方案: ${name}` });
      const res = await fetchProfiles();
      setProfiles(Array.isArray(res) ? res : []);
      if (selectedProfileName === name) setSelectedProfileName('');
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '删除失败' });
    }
  }, [profiles, selectedProfileName]);

  const handleSaveAsProfile = useCallback(async () => {
    const name = prompt('请输入新方案名称');
    const trimmed = name?.trim();
    if (!trimmed) return;
    await handleExportProfile(trimmed);
    setSelectedProfileName(trimmed);
  }, [handleExportProfile]);

  /* ─── Field updaters ─── */
  const updateModelField = useCallback(
    (target: 'primary' | 'fallback', field: string, value: string | number) => {
      setConfig((prev) => {
        const models = { ...prev.models };
        if (target === 'primary') {
          models.primary = { ...models.primary, [field]: value } as typeof models.primary;
        } else {
          const fb = models.fallback || models.primary;
          models.fallback = { ...fb, [field]: value } as typeof models.primary;
        }
        return { ...prev, models };
      });
    },
    [],
  );

  const updateExtraction = useCallback((field: keyof ConfigExtraction, value: unknown) => {
    setConfig((prev) => ({
      ...prev,
      extraction: { ...prev.extraction, [field]: value },
    }));
  }, []);

  const updatePriority = useCallback((key: PriorityKey, value: number) => {
    setConfig((prev) => ({
      ...prev,
      priorities: { weights: { ...prev.priorities.weights, [key]: value } },
    }));
  }, []);

  const updateConfidenceWeight = useCallback((key: keyof ConfidenceWeights, value: number) => {
    setConfig((prev) => ({
      ...prev,
      confidence: {
        ...prev.confidence,
        weights: { ...prev.confidence.weights, [key]: value },
      },
    }));
  }, []);

  const updateConfidenceThreshold = useCallback((value: number) => {
    setConfig((prev) => ({
      ...prev,
      confidence: { ...prev.confidence, threshold_review: value },
    }));
  }, []);

  const updateConcurrency = useCallback((field: keyof ConfigConcurrency, value: number) => {
    setConfig((prev) => ({
      ...prev,
      concurrency: { ...prev.concurrency, [field]: value },
    }));
  }, []);

  const updateOcr = useCallback((field: keyof ConfigOcr, value: boolean | string) => {
    setConfig((prev) => ({
      ...prev,
      ocr: { ...prev.ocr, [field]: value },
    }));
  }, []);

  const updateBudget = useCallback((field: keyof ConfigBudget, value: number | boolean) => {
    setConfig((prev) => ({
      ...prev,
      budget: { ...prev.budget, [field]: value },
    }));
  }, []);

  const updateStorage = useCallback((field: keyof ConfigStorage, value: string) => {
    setConfig((prev) => ({
      ...prev,
      storage: { ...prev.storage, [field]: value },
    }));
  }, []);

  const copyFromPrimary = useCallback(() => {
    setConfig((prev) => ({
      ...prev,
      models: {
        ...prev.models,
        fallback: { ...prev.models.primary },
      },
    }));
  }, []);

  // 防御性读取：v1.1 后端返回 5 项（含 fidelity）；旧版本只有 4 项。
  // 如果 config.confidence 因任何原因为 undefined，渲染前给一个默认值兜底，
  // 不让 React 在 .weights.self 处 throw。
  const weights = config.confidence?.weights ?? {
    self: 0.25,
    consistency: 0.25,
    struct: 0.15,
    conflict: 0.05,
    fidelity: 0.30,
  };
  const weightSum =
    (weights.self ?? 0) +
    (weights.consistency ?? 0) +
    (weights.struct ?? 0) +
    (weights.conflict ?? 0) +
    ((weights as { fidelity?: number }).fidelity ?? 0);
  const weightSumOk = Math.abs(weightSum - 1) < 0.001;

  /* ─── Render ─── */
  return (
    <div className="fixed inset-0 z-50 flex animate-fade-in">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Drawer panel */}
      <div className="relative ml-auto w-full max-w-2xl bg-white shadow-2xl overflow-y-auto h-full animate-slide-in">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-air-border px-6 py-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">
            <span className="inline-block pb-1 border-b-2 border-primary">系统配置</span>
          </h2>
          <div className="flex items-center gap-3">
            {message && (
              <span
                className={`text-sm font-medium ${
                  message.type === 'success' ? 'text-emerald-600' : 'text-red-500'
                }`}
              >
                {message.text}
              </span>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="btn-primary"
            >
              {saving ? '保存中...' : '保存为全局默认'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-btn hover:bg-air-hover"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-6">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-primary/20 border-t-primary" />
              <span className="ml-3 text-gray-400">加载配置中...</span>
            </div>
          ) : (
            <>
              {/* ─── 方案管理 ─── */}
              <div className="card p-5 mb-4 border-l-[3px] border-l-primary">
                <h3 className="text-base font-semibold text-gray-900 mb-4">方案管理</h3>
                <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto_auto] gap-3 items-end">
                  <div>
                    <Label htmlFor="profile-select">当前方案</Label>
                    <select
                      id="profile-select"
                      value={selectedProfileName}
                      onChange={(e) => {
                        const name = e.target.value;
                        setSelectedProfileName(name);
                        if (name) handleImportProfile(name);
                      }}
                      className="select-field"
                    >
                      <option value="">通用 / 未选择方案</option>
                      {profiles.map((profile) => (
                        <option key={profile.name} value={profile.name}>
                          {profile.label || profile.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button type="button" onClick={handleSaveAsProfile} className="btn-secondary text-sm">
                    另存为方案
                  </button>
                  <button
                    type="button"
                    onClick={() => handleImportProfile(selectedProfileName)}
                    disabled={!selectedProfileName}
                    className="btn-secondary text-sm"
                  >
                    导入方案
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteProfile(selectedProfileName)}
                    disabled={!selectedProfileName}
                    className="btn-danger text-sm"
                  >
                    删除方案
                  </button>
                </div>
                <div className="text-xs text-gray-400 mt-3">
                  方案会注入行业词表和关注要点；保存为全局默认会写入当前系统配置。
                </div>
              </div>

              {/* ─── 模型配置 ─── */}
              <CollapsibleSection title="模型配置" defaultOpen>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="primary-provider">主模型 Provider</Label>
                    <select
                      id="primary-provider"
                      value={config.models.primary.provider}
                      onChange={(e) => updateModelField('primary', 'provider', e.target.value)}
                      className="select-field"
                    >
                      <option value="openai">OpenAI</option>
                      <option value="azure">Azure OpenAI</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="zhipu">智谱 GLM</option>
                      <option value="qwen">通义千问</option>
                      <option value="moonshot">Moonshot</option>
                      <option value="custom">自定义</option>
                    </select>
                  </div>
                  <div>
                    <Label htmlFor="primary-model">主模型 Model</Label>
                    <input
                      id="primary-model"
                      type="text"
                      value={config.models.primary.model}
                      onChange={(e) => updateModelField('primary', 'model', e.target.value)}
                      className="input-field"
                    />
                  </div>
                  <div>
                    <Label htmlFor="primary-key">API Key</Label>
                    <input
                      id="primary-key"
                      type="password"
                      value={config.models.primary.api_key}
                      onChange={(e) => updateModelField('primary', 'api_key', e.target.value)}
                      className="input-field"
                      placeholder="sk-..."
                    />
                  </div>
                  <div>
                    <Label htmlFor="primary-base">Base URL</Label>
                    <input
                      id="primary-base"
                      type="text"
                      value={config.models.primary.base_url}
                      onChange={(e) => updateModelField('primary', 'base_url', e.target.value)}
                      className="input-field"
                      placeholder="https://api.openai.com/v1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="primary-rpm">RPM (每分钟请求数)</Label>
                    <input
                      id="primary-rpm"
                      type="number"
                      value={config.models.primary.rpm_limit}
                      onChange={(e) => updateModelField('primary', 'rpm_limit', Number(e.target.value))}
                      className="input-field"
                      min={1}
                    />
                  </div>
                  <div>
                    <Label htmlFor="primary-tpm">TPM (每分钟Token数)</Label>
                    <input
                      id="primary-tpm"
                      type="number"
                      value={config.models.primary.tpm_limit}
                      onChange={(e) => updateModelField('primary', 'tpm_limit', Number(e.target.value))}
                      className="input-field"
                      min={1}
                    />
                  </div>
                </div>

                {/* Fallback model toggle */}
                <div className="mt-4 pt-4 border-t border-air-border">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-600 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!config.models.fallback}
                      onChange={(e) => {
                        if (e.target.checked) {
                          copyFromPrimary();
                        } else {
                          setConfig((prev) => ({
                            ...prev,
                            models: { ...prev.models, fallback: null },
                          }));
                        }
                      }}
                      className="rounded border-gray-300 text-primary focus:ring-primary/30"
                    />
                    启用备用模型
                  </label>

                  {config.models.fallback && (
                    <div className="grid grid-cols-2 gap-4 mt-3 ml-6 p-4 bg-gray-50 rounded-card">
                      <div>
                        <Label htmlFor="fallback-provider">备用 Provider</Label>
                        <select
                          id="fallback-provider"
                          value={config.models.fallback.provider}
                          onChange={(e) => updateModelField('fallback', 'provider', e.target.value)}
                          className="select-field"
                        >
                          <option value="openai">OpenAI</option>
                          <option value="azure">Azure OpenAI</option>
                          <option value="deepseek">DeepSeek</option>
                          <option value="zhipu">智谱 GLM</option>
                          <option value="qwen">通义千问</option>
                          <option value="moonshot">Moonshot</option>
                          <option value="custom">自定义</option>
                        </select>
                      </div>
                      <div>
                        <Label htmlFor="fallback-model">备用 Model</Label>
                        <input
                          id="fallback-model"
                          type="text"
                          value={config.models.fallback.model}
                          onChange={(e) => updateModelField('fallback', 'model', e.target.value)}
                          className="input-field"
                        />
                      </div>
                      <div>
                        <Label htmlFor="fallback-key">API Key</Label>
                        <input
                          id="fallback-key"
                          type="password"
                          value={config.models.fallback.api_key}
                          onChange={(e) => updateModelField('fallback', 'api_key', e.target.value)}
                          className="input-field"
                        />
                      </div>
                      <div>
                        <Label htmlFor="fallback-base">Base URL</Label>
                        <input
                          id="fallback-base"
                          type="text"
                          value={config.models.fallback.base_url}
                          onChange={(e) => updateModelField('fallback', 'base_url', e.target.value)}
                          className="input-field"
                        />
                      </div>
                      <div>
                        <Label htmlFor="fallback-rpm">RPM</Label>
                        <input
                          id="fallback-rpm"
                          type="number"
                          value={config.models.fallback.rpm_limit}
                          onChange={(e) => updateModelField('fallback', 'rpm_limit', Number(e.target.value))}
                          className="input-field"
                        />
                      </div>
                      <div>
                        <Label htmlFor="fallback-tpm">TPM</Label>
                        <input
                          id="fallback-tpm"
                          type="number"
                          value={config.models.fallback.tpm_limit}
                          onChange={(e) => updateModelField('fallback', 'tpm_limit', Number(e.target.value))}
                          className="input-field"
                        />
                      </div>
                    </div>
                  )}
                </div>
              </CollapsibleSection>

              {/* ─── 抽取配置 ─── */}
              <CollapsibleSection title="抽取配置">
                <div className="space-y-4">
                  <div>
                    <Label>抽取粒度</Label>
                    <div className="flex gap-6 mt-1">
                      {(['fine', 'balanced'] as const).map((g) => (
                        <label
                          key={g}
                          className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer"
                        >
                          <input
                            type="radio"
                            name="granularity"
                            value={g}
                            checked={config.extraction.granularity === g}
                            onChange={(e) => updateExtraction('granularity', e.target.value)}
                            className="text-primary focus:ring-primary/30"
                          />
                          {g === 'fine' ? '精细' : '平衡'}
                        </label>
                      ))}
                    </div>
                  </div>

                  <div>
                    <Label>法规深度</Label>
                    <div className="flex gap-6 mt-1">
                      {(['full', 'limited'] as const).map((d) => (
                        <label
                          key={d}
                          className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer"
                        >
                          <input
                            type="radio"
                            name="regulation_depth"
                            value={d}
                            checked={config.extraction.regulation_depth === d}
                            onChange={(e) => updateExtraction('regulation_depth', e.target.value)}
                            className="text-primary focus:ring-primary/30"
                          />
                          {d === 'full' ? '完整条款' : '摘要要点'}
                        </label>
                      ))}
                    </div>
                  </div>

                  <div>
                    <Label htmlFor="industry-vocab">行业词汇 (每行一个)</Label>
                    <textarea
                      id="industry-vocab"
                      value={config.extraction.industry_vocabulary}
                      onChange={(e) => updateExtraction('industry_vocabulary', e.target.value)}
                      rows={14}
                      className="input-field font-mono text-xs"
                      placeholder="供应链金融&#10;保理&#10;福费廷"
                    />
                  </div>

                  <div>
                    <Label htmlFor="focus-points">行业关注要点 (每行一个)</Label>
                    <textarea
                      id="focus-points"
                      value={config.extraction.industry_focus_points}
                      onChange={(e) => updateExtraction('industry_focus_points', e.target.value)}
                      rows={8}
                      className="input-field text-xs"
                      placeholder="数据跨境传输合规&#10;个人信息保护&#10;反商业贿赂"
                    />
                  </div>

                  <div>
                    <Label>红线关键词</Label>
                    <RedlineKeywordsPicker
                      selected={config.extraction.redline_keywords}
                      onChange={(tags) => updateExtraction('redline_keywords', tags)}
                    />
                  </div>
                </div>
              </CollapsibleSection>

              {/* ─── 优先级配置 ─── */}
              <CollapsibleSection title="优先级配置">
                <div className="space-y-3">
                  {([
                    { key: '法规' as PriorityKey, label: '法规', desc: '法律法规、司法解释' },
                    { key: '公司红线' as PriorityKey, label: '公司红线', desc: '公司不可接受条款' },
                    { key: '内部制度' as PriorityKey, label: '内部制度', desc: '公司内部合规制度' },
                    { key: '标准条款库' as PriorityKey, label: '标准条款库', desc: '标准合同条款模板' },
                    { key: '历史合同' as PriorityKey, label: '历史合同', desc: '历史合同中提取的规则' },
                  ]).map((item) => (
                    <div
                      key={item.key}
                      className="flex items-center gap-4 py-2 px-3 bg-gray-50 rounded-input"
                    >
                      <span className="w-8 h-8 flex items-center justify-center rounded-full bg-primary text-white text-sm font-bold">
                        {config.priorities.weights[item.key]}
                      </span>
                      <div className="flex-1">
                        <div className="text-sm font-medium text-gray-900">{item.label}</div>
                        <div className="text-xs text-gray-400">{item.desc}</div>
                      </div>
                      <input
                        type="number"
                        value={config.priorities.weights[item.key]}
                        onChange={(e) => updatePriority(item.key, Number(e.target.value))}
                        min={1}
                        max={5}
                        className="w-20 input-field text-center"
                      />
                    </div>
                  ))}
                </div>
              </CollapsibleSection>

              {/* ─── 置信度配置 ─── */}
              <CollapsibleSection title="置信度配置">
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between">
                      <Label>人工复核阈值</Label>
                      <span className="text-sm text-primary font-semibold">
                        {config.confidence.threshold_review.toFixed(2)}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.01}
                      value={config.confidence.threshold_review}
                      onChange={(e) => updateConfidenceThreshold(Number(e.target.value))}
                      className="w-full mt-1 accent-primary"
                    />
                    <div className="flex justify-between text-xs text-gray-400">
                      <span>0</span>
                      <span>1</span>
                    </div>
                    <p className="text-xs text-gray-400 mt-1">
                      低于此阈值的规则标记为"需人工复核"
                    </p>
                  </div>

                  <div className="pt-3 border-t border-air-border">
                    <Label>权重分配 (必须总和为 1.0)</Label>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-1">
                      {([
                        { key: 'self' as keyof ConfidenceWeights, label: '模型自评' },
                        { key: 'consistency' as keyof ConfidenceWeights, label: '一致性双采样' },
                        { key: 'struct' as keyof ConfidenceWeights, label: '结构校验' },
                        { key: 'conflict' as keyof ConfidenceWeights, label: '冲突标记' },
                        { key: 'fidelity' as keyof ConfidenceWeights, label: '数值忠实度', highlight: true },
                      ]).map((w) => (
                        <div key={w.key} className={w.highlight ? 'p-3 rounded-input bg-primary-soft border border-primary/20' : ''}>
                          <Label htmlFor={w.key}>{w.label}</Label>
                          <input
                            id={w.key}
                            type="number"
                            value={(weights[w.key] ?? 0).toFixed(2)}
                            onChange={(e) => updateConfidenceWeight(w.key, Number(e.target.value))}
                            min={0}
                            max={1}
                            step={0.01}
                            className="input-field"
                          />
                          <div className="mt-1 text-xs text-gray-400">
                            {(weights[w.key] ?? 0).toFixed(2)}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 text-sm">
                      <span
                        className={
                          weightSumOk
                            ? 'text-emerald-600'
                            : 'text-red-500 font-bold'
                        }
                      >
                        当前总和: {weightSum.toFixed(2)}
                      </span>
                    </div>
                  </div>
                </div>
              </CollapsibleSection>

              {/* ─── 并发配置 ─── */}
              <CollapsibleSection title="并发配置">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="concur-files">最大并行文件数</Label>
                    <input
                      id="concur-files"
                      type="number"
                      value={config.concurrency.files}
                      onChange={(e) => updateConcurrency('files', Number(e.target.value))}
                      className="input-field"
                      min={1}
                      max={20}
                    />
                  </div>
                  <div>
                    <Label htmlFor="concur-blocks">最大并行块数 (每文件)</Label>
                    <input
                      id="concur-blocks"
                      type="number"
                      value={config.concurrency.blocks}
                      onChange={(e) => updateConcurrency('blocks', Number(e.target.value))}
                      className="input-field"
                      min={1}
                      max={50}
                    />
                  </div>
                </div>
              </CollapsibleSection>

              {/* ─── OCR 配置 ─── */}
              <CollapsibleSection title="OCR 配置">
                <div className="space-y-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.ocr.enabled}
                      onChange={(e) => updateOcr('enabled', e.target.checked)}
                      className="rounded border-gray-300 text-primary focus:ring-primary/30"
                    />
                    <span className="text-sm text-gray-600">
                      对扫描件 PDF 启用 OCR 文字识别
                    </span>
                  </label>
                  {config.ocr.enabled && (
                    <div>
                      <Label htmlFor="ocr-engine">OCR 引擎</Label>
                      <select
                        id="ocr-engine"
                        value={config.ocr.engine}
                        onChange={(e) => updateOcr('engine', e.target.value)}
                        className="select-field max-w-xs"
                      >
                        <option value="paddleocr">PaddleOCR</option>
                        <option value="tesseract">Tesseract</option>
                        <option value="azure-form">Azure Form Recognizer</option>
                      </select>
                    </div>
                  )}
                </div>
              </CollapsibleSection>

              {/* ─── 预算配置 ─── */}
              <CollapsibleSection title="预算配置">
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="max-tokens">单批次最大 Token 数</Label>
                    <input
                      id="max-tokens"
                      type="number"
                      value={config.budget.max_tokens_per_batch}
                      onChange={(e) => updateBudget('max_tokens_per_batch', Number(e.target.value))}
                      className="input-field max-w-xs"
                      min={10000}
                      step={10000}
                    />
                  </div>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.budget.pause_on_overrun}
                      onChange={(e) => updateBudget('pause_on_overrun', e.target.checked)}
                      className="rounded border-gray-300 text-primary focus:ring-primary/30"
                    />
                    <span className="text-sm text-gray-600">超出预算时暂停并等待确认</span>
                  </label>
                </div>
              </CollapsibleSection>

              {/* ─── 存储配置 ─── */}
              <CollapsibleSection title="存储配置">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label htmlFor="db-path">数据库路径</Label>
                    <input
                      id="db-path"
                      type="text"
                      value={config.storage.db_path}
                      onChange={(e) => updateStorage('db_path', e.target.value)}
                      className="input-field"
                    />
                  </div>
                  <div>
                    <Label htmlFor="exports-dir">导出目录</Label>
                    <input
                      id="exports-dir"
                      type="text"
                      value={config.storage.exports_dir}
                      onChange={(e) => updateStorage('exports_dir', e.target.value)}
                      className="input-field"
                    />
                  </div>
                </div>
              </CollapsibleSection>

              {/* Bottom padding for scroll comfort */}
              <div className="h-8" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
