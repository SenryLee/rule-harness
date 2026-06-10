import { useEffect, useMemo, useState } from 'react';
import { fetchConfig, updateConfig } from '../api';
import type { Config, ConfigModels, ModelConfig, PriorityKey } from '../api';
import { Icon } from './Ui';

type SettingsTab = 'model' | 'extraction' | 'priority' | 'confidence' | 'advanced';

const TABS: Array<{ key: SettingsTab; label: string }> = [
  { key: 'model', label: '模型配置' },
  { key: 'extraction', label: '抽取配置' },
  { key: 'priority', label: '优先级' },
  { key: 'confidence', label: '置信度' },
  { key: 'advanced', label: '高级' },
];

const PROFILE_OPTIONS = ['建工·总包', '建工·勘察设计', '房地产', '金融', '医药', 'IT', '制造', '能源·电力', '汽车', '通用商事'];
const PRIORITY_ITEMS: Array<{ key: PriorityKey; desc: string }> = [
  { key: '法规', desc: '法律法规、司法解释' },
  { key: '公司红线', desc: '公司不可接受条款' },
  { key: '内部制度', desc: '公司内部合规制度' },
  { key: '标准条款库', desc: '标准合同条款模板' },
  { key: '历史合同', desc: '历史合同中提取的规则' },
];
const REDLINE_PRESETS = [
  { group: '强义务 / 禁止', words: ['不得', '禁止', '必须', '应当', '严禁', '红线', '重大', '无效'] },
  { group: '责任与赔偿', words: ['无限责任', '最高限额', '赔偿上限', '违约金', '损害赔偿', '间接损失', '可得利益', '惩罚性赔偿'] },
  { group: '争议解决与法律适用', words: ['仲裁', '管辖', '法律适用', '法律选择', '不可转让'] },
  { group: '合规高敏', words: ['反贿赂', '反洗钱', '数据出境', '个人信息', '制裁', '独占许可', '排他许可', '永久许可', '全球范围'] },
];

const PROVIDERS = ['openai', 'deepseek', 'mimo', 'zhipu', 'qwen', 'moonshot'];

const PROVIDER_PRESETS: Record<string, Partial<ModelConfig>> = {
  mimo: {
    base_url: 'https://api.xiaomimimo.com/v1',
    model: 'mimo-v2.5-pro',
    rpm_limit: 60,
    tpm_limit: 200000,
  },
  deepseek: {
    base_url: 'https://api.deepseek.com/v1',
  },
  qwen: {
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'deepseek-v4-flash',
    rpm_limit: 60,
    tpm_limit: 200000,
  },
  openai: {
    base_url: 'https://api.openai.com/v1',
  },
};

function toNumber(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-semibold text-[var(--text-secondary)]">{label}</span>
      {children}
    </label>
  );
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <section className={`card p-5 ${className}`}>{children}</section>;
}

function TabBar({ active, onChange }: { active: SettingsTab; onChange: (tab: SettingsTab) => void }) {
  return (
    <div className="mb-5 flex border-b border-[var(--border)]">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`relative px-4 py-3 text-sm font-semibold transition-colors ${
            active === tab.key ? 'text-[var(--primary)]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
          }`}
        >
          {tab.label}
          {active === tab.key && <span className="absolute inset-x-0 bottom-[-1px] h-0.5 rounded-full bg-[var(--primary)]" />}
        </button>
      ))}
    </div>
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`input-field mt-0 ${props.className || ''}`} />;
}

function SelectInput(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`select-field mt-0 ${props.className || ''}`} />;
}

export default function SettingsView() {
  const [config, setConfig] = useState<Config | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTab>('model');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [customKeyword, setCustomKeyword] = useState('');
  const [primaryApiKeyDraft, setPrimaryApiKeyDraft] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchConfig()
      .then((data) => {
        if (!cancelled) setConfig(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setMessage(err.message || '配置加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const weightSum = useMemo(() => {
    if (!config) return 0;
    const w = config.confidence.weights;
    return (w.self || 0) + (w.consistency || 0) + (w.struct || 0) + (w.conflict || 0) + (w.fidelity || 0);
  }, [config]);

  function patchModel(slot: keyof ConfigModels, patch: Partial<ModelConfig>) {
    setConfig((prev) => {
      if (!prev) return prev;
      const current = prev.models[slot] || {
        provider: 'openai',
        api_key: '',
        base_url: '',
        model: '',
        rpm_limit: 60,
        tpm_limit: 100000,
      };
      return { ...prev, models: { ...prev.models, [slot]: { ...current, ...patch } } };
    });
  }

  function selectProvider(slot: keyof ConfigModels, provider: string) {
    patchModel(slot, { provider, ...(PROVIDER_PRESETS[provider] || {}) });
  }

  function toggleKeyword(word: string) {
    setConfig((prev) => {
      if (!prev) return prev;
      const current = prev.extraction.redline_keywords || [];
      const next = current.includes(word) ? current.filter((item) => item !== word) : [...current, word];
      return { ...prev, extraction: { ...prev.extraction, redline_keywords: next } };
    });
  }

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    setMessage(null);
    try {
      await updateConfig({
        ...config,
        models: {
          ...config.models,
          primary: {
            ...config.models.primary,
            api_key: primaryApiKeyDraft || config.models.primary.api_key,
          },
        },
      });
      setMessage('配置已保存');
      setPrimaryApiKeyDraft('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--primary-light)] border-t-[var(--primary)]" />
        <span className="ml-3 text-sm text-[var(--text-muted)]">加载配置...</span>
      </div>
    );
  }

  if (!config) {
    return <div className="card mx-auto max-w-2xl p-5 text-sm text-red-600">{message || '配置加载失败'}</div>;
  }

  const redlineSelected = config.extraction.redline_keywords || [];
  const allPresetWords = REDLINE_PRESETS.flatMap((group) => group.words);

  return (
    <div className="anim-fade-in mx-auto max-w-[920px]">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--text-primary)]">系统设置</h1>
          <p className="mt-1 text-[13px] text-[var(--text-muted)]">配置模型、抽取参数和系统行为</p>
        </div>
        <div className="flex items-center gap-3">
          {message && (
            <span className={`text-sm font-semibold ${message.includes('失败') ? 'text-red-600' : 'text-emerald-600'}`}>
              {message}
            </span>
          )}
          <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>
      </div>

      <Card className="mb-5 border-l-[3px] border-l-[var(--primary)]">
        <div className="flex items-end gap-4">
          <Field label="当前方案">
            <SelectInput
              value={config.extraction.industry_preset || ''}
              onChange={(event) =>
                setConfig({ ...config, extraction: { ...config.extraction, industry_preset: event.target.value || null } })
              }
            >
              <option value="">通用 / 未选择方案</option>
              {PROFILE_OPTIONS.map((profile) => (
                <option key={profile} value={profile}>
                  {profile}
                </option>
              ))}
            </SelectInput>
          </Field>
          <button type="button" className="btn-secondary text-sm" disabled>
            导入方案
          </button>
          <button type="button" className="btn-secondary text-sm" disabled>
            另存为
          </button>
        </div>
      </Card>

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === 'model' && (
        <div className="anim-fade-in-up space-y-4">
          <Card>
            <h2 className="mb-4 text-sm font-bold text-[var(--text-primary)]">主模型</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Field label="Provider">
                <SelectInput value={config.models.primary.provider} onChange={(event) => selectProvider('primary', event.target.value)}>
                  {PROVIDERS.map((provider) => (
                    <option key={provider} value={provider}>{provider}</option>
                  ))}
                </SelectInput>
              </Field>
              <Field label="Model">
                <TextInput value={config.models.primary.model} onChange={(event) => patchModel('primary', { model: event.target.value })} />
              </Field>
              <Field label="API Key">
                <TextInput
                  type="password"
                  value={primaryApiKeyDraft}
                  placeholder={config.models.primary.api_key ? '已配置，输入新 Key 后覆盖' : '使用前输入 API Key'}
                  onChange={(event) => setPrimaryApiKeyDraft(event.target.value)}
                />
              </Field>
              <Field label="Base URL">
                <TextInput value={config.models.primary.base_url || ''} onChange={(event) => patchModel('primary', { base_url: event.target.value })} />
              </Field>
              <Field label="RPM (每分钟请求数)">
                <TextInput type="number" value={config.models.primary.rpm_limit} onChange={(event) => patchModel('primary', { rpm_limit: toNumber(event.target.value, 60) })} />
              </Field>
              <Field label="TPM (每分钟Token数)">
                <TextInput type="number" value={config.models.primary.tpm_limit} onChange={(event) => patchModel('primary', { tpm_limit: toNumber(event.target.value, 100000) })} />
              </Field>
            </div>
          </Card>
          <Card>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={!!config.models.fallback}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    models: {
                      ...config.models,
                      fallback: event.target.checked
                        ? { provider: 'openai', api_key: '', base_url: '', model: '', rpm_limit: 30, tpm_limit: 50000 }
                        : null,
                    },
                  })
                }
              />
              启用备用模型
            </label>
          </Card>
        </div>
      )}

      {activeTab === 'extraction' && (
        <div className="anim-fade-in-up space-y-4">
          <Card>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <Field label={`抽取颗粒度：${config.extraction.granularity_level ?? 3} 档（1 粗 — 5 极细）`}>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={config.extraction.granularity_level ?? 3}
                  onChange={(event) => {
                    const level = Number(event.target.value);
                    setConfig({
                      ...config,
                      extraction: {
                        ...config.extraction,
                        granularity_level: level,
                        granularity: level >= 4 ? 'fine' : 'balanced',
                      },
                    });
                  }}
                  className="w-full accent-[var(--accent)]"
                />
              </Field>
              <Field label="法规深度">
                <SelectInput
                  value={config.extraction.regulation_depth}
                  onChange={(event) => setConfig({ ...config, extraction: { ...config.extraction, regulation_depth: event.target.value as 'full' | 'limited' } })}
                >
                  <option value="full">完整条款</option>
                  <option value="limited">摘要要点</option>
                </SelectInput>
              </Field>
            </div>
          </Card>

          <Card>
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-[var(--text-primary)]">红线关键词</h2>
                <p className="mt-1 text-xs text-[var(--text-muted)]">已选 {redlineSelected.length} 项</p>
              </div>
              <button
                type="button"
                className="text-xs font-semibold text-[var(--primary)]"
                onClick={() =>
                  setConfig({
                    ...config,
                    extraction: {
                      ...config.extraction,
                      redline_keywords: redlineSelected.length === allPresetWords.length ? [] : allPresetWords,
                    },
                  })
                }
              >
                {redlineSelected.length === allPresetWords.length ? '清空预设' : '全选预设'}
              </button>
            </div>
            <div className="space-y-4">
              {REDLINE_PRESETS.map((group) => (
                <div key={group.group}>
                  <div className="mb-2 text-xs font-bold text-[var(--text-muted)]">{group.group}</div>
                  <div className="flex flex-wrap gap-2">
                    {group.words.map((word) => {
                      const checked = redlineSelected.includes(word);
                      return (
                        <button
                          key={word}
                          type="button"
                          onClick={() => toggleKeyword(word)}
                          className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold transition-all ${
                            checked
                              ? 'border-[var(--primary)] bg-[var(--primary)] text-white'
                              : 'border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--primary)]'
                          }`}
                        >
                          {checked && <Icon name="check" size={12} strokeWidth={2.5} />}
                          {word}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-2">
              <TextInput value={customKeyword} onChange={(event) => setCustomKeyword(event.target.value)} placeholder="输入自定义关键词" />
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  const word = customKeyword.trim();
                  if (word) toggleKeyword(word);
                  setCustomKeyword('');
                }}
              >
                添加
              </button>
            </div>
          </Card>

          <Card>
            <Field label="行业词汇">
              <textarea
                value={config.extraction.industry_vocabulary || ''}
                onChange={(event) => setConfig({ ...config, extraction: { ...config.extraction, industry_vocabulary: event.target.value } })}
                className="input-field mt-0 min-h-[120px] font-mono leading-7"
              />
            </Field>
          </Card>
        </div>
      )}

      {activeTab === 'priority' && (
        <Card className="anim-fade-in-up">
          <h2 className="mb-1 text-sm font-bold text-[var(--text-primary)]">优先级权重</h2>
          <p className="mb-4 text-xs text-[var(--text-muted)]">数字越小优先级越高。高优先级来源的规则覆盖低优先级来源。</p>
          <div className="space-y-2">
            {PRIORITY_ITEMS.map((item) => (
              <div key={item.key} className="flex items-center gap-4 rounded-md bg-[var(--bg-hover)] px-4 py-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--primary)] text-sm font-bold text-white">
                  {config.priorities.weights[item.key]}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-bold text-[var(--text-primary)]">{item.key}</div>
                  <div className="text-xs text-[var(--text-muted)]">{item.desc}</div>
                </div>
                <TextInput
                  type="number"
                  min={1}
                  max={5}
                  value={config.priorities.weights[item.key]}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      priorities: {
                        weights: { ...config.priorities.weights, [item.key]: toNumber(event.target.value, config.priorities.weights[item.key]) },
                      },
                    })
                  }
                  className="w-20 text-center"
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {activeTab === 'confidence' && (
        <div className="anim-fade-in-up space-y-4">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-[var(--text-primary)]">人工复核阈值</h2>
                <p className="mt-1 text-xs text-[var(--text-muted)]">低于此值的规则标记为“需人工复核”</p>
              </div>
              <span className="font-mono text-xl font-bold text-[var(--primary)]">{config.confidence.threshold_review.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={config.confidence.threshold_review}
              onChange={(event) => setConfig({ ...config, confidence: { ...config.confidence, threshold_review: Number(event.target.value) } })}
              className="w-full accent-[var(--primary)]"
            />
          </Card>
          <Card>
            <h2 className="mb-1 text-sm font-bold text-[var(--text-primary)]">权重分配</h2>
            <p className="mb-4 text-xs text-[var(--text-muted)]">五项权重总和必须为 1.0</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
              {(['self', 'consistency', 'struct', 'conflict', 'fidelity'] as const).map((key) => (
                <Field key={key} label={key}>
                  <TextInput
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={config.confidence.weights[key] ?? 0}
                    onChange={(event) =>
                      setConfig({
                        ...config,
                        confidence: {
                          ...config.confidence,
                          weights: { ...config.confidence.weights, [key]: Number(event.target.value) },
                        },
                      })
                    }
                    className="text-center font-mono"
                  />
                </Field>
              ))}
            </div>
            <div className={`mt-3 text-sm font-bold ${Math.abs(weightSum - 1) < 0.01 ? 'text-emerald-600' : 'text-red-600'}`}>
              当前总和: {weightSum.toFixed(2)} {Math.abs(weightSum - 1) < 0.01 ? '✓' : '(需要 = 1.00)'}
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'advanced' && (
        <div className="anim-fade-in-up space-y-4">
          <Card>
            <h2 className="mb-4 text-sm font-bold text-[var(--text-primary)]">并发配置</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Field label="最大并行文件数">
                <TextInput type="number" value={config.concurrency.files} onChange={(event) => setConfig({ ...config, concurrency: { ...config.concurrency, files: toNumber(event.target.value, 3) } })} />
              </Field>
              <Field label="最大并行块数">
                <TextInput type="number" value={config.concurrency.blocks} onChange={(event) => setConfig({ ...config, concurrency: { ...config.concurrency, blocks: toNumber(event.target.value, 5) } })} />
              </Field>
            </div>
          </Card>
          <Card>
            <h2 className="mb-4 text-sm font-bold text-[var(--text-primary)]">OCR 配置</h2>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input type="checkbox" checked={config.ocr.enabled} onChange={(event) => setConfig({ ...config, ocr: { ...config.ocr, enabled: event.target.checked } })} />
              对扫描件 PDF 启用 OCR 文字识别
            </label>
          </Card>
          <Card>
            <h2 className="mb-4 text-sm font-bold text-[var(--text-primary)]">预算配置</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Field label="单批次最大 Token 数">
                <TextInput type="number" value={config.budget.max_tokens_per_batch} onChange={(event) => setConfig({ ...config, budget: { ...config.budget, max_tokens_per_batch: toNumber(event.target.value, 500000) } })} />
              </Field>
              <label className="flex items-end gap-2 pb-2 text-sm text-[var(--text-secondary)]">
                <input type="checkbox" checked={config.budget.pause_on_overrun} onChange={(event) => setConfig({ ...config, budget: { ...config.budget, pause_on_overrun: event.target.checked } })} />
                超出预算时暂停
              </label>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
