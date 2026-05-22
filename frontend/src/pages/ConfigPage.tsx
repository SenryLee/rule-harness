import { useState, useEffect, useCallback } from 'react'
import {
  fetchConfig,
  updateConfig,
  fetchProfiles,
  saveProfile,
  deleteProfile,
} from '../api'
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
} from '../api'

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
      struct: 0.25,
      conflict: 0.25,
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
}

const checkboxClasses =
  'rounded border-codex-border bg-codex-bg text-accent focus:ring-accent/50 focus:ring-offset-0'

const radioClasses =
  'text-accent focus:ring-accent/50 focus:ring-offset-0'

function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className={`card mb-4 transition-colors ${
        open ? 'border-l-[3px] border-l-accent' : ''
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 text-left group"
      >
        <h3 className="text-base font-display text-codex-text-primary group-hover:text-accent transition-colors">
          {title}
        </h3>
        <svg
          className={`w-5 h-5 text-codex-text-muted transition-transform group-hover:text-accent ${
            open ? 'rotate-180' : ''
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ease-out ${
          open ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-5 pb-4">{children}</div>
      </div>
    </div>
  )
}

function Label({
  children,
  htmlFor,
}: {
  children: React.ReactNode
  htmlFor?: string
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-sm font-medium text-codex-text-secondary mb-1.5"
    >
      {children}
    </label>
  )
}

function TagInput({
  tags,
  onChange,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
}) {
  const [input, setInput] = useState('')

  const addTag = useCallback(() => {
    const trimmed = input.trim()
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed])
      setInput('')
    }
  }, [input, tags, onChange])

  const removeTag = useCallback(
    (index: number) => {
      onChange(tags.filter((_, i) => i !== index))
    },
    [tags, onChange]
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        addTag()
      }
    },
    [addTag]
  )

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {tags.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-accent-soft text-accent border border-accent/20"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(i)}
              className="text-accent/70 hover:text-accent transition-colors"
            >
              &times;
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入后按回车添加"
          className="input-field flex-1"
        />
        <button type="button" onClick={addTag} className="btn-secondary text-sm">
          添加
        </button>
      </div>
    </div>
  )
}

export default function ConfigPage() {
  const [config, setConfig] = useState<Config>(DEFAULT_CONFIG)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [newProfileName, setNewProfileName] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchConfig()
      .then((cfg) => {
        if (!cancelled) {
          if (cfg.models.fallback && !cfg.models.fallback.provider) {
            cfg = { ...cfg, models: { ...cfg.models, fallback: null } }
          }
          setConfig(cfg)
        }
      })
      .catch((err) => {
        if (!cancelled) setMessage({ type: 'error', text: err.message })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    fetchProfiles()
      .then((res) => {
        if (!cancelled) setProfiles(Array.isArray(res) ? res : [])
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setMessage(null)
    try {
      await updateConfig(config)
      setMessage({ type: 'success', text: '配置已保存' })
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '保存失败' })
    } finally {
      setSaving(false)
    }
  }, [config])

  const handleExportProfile = useCallback(async (profileName: string) => {
    try {
      await saveProfile(profileName, config)
      setMessage({ type: 'success', text: `配置已导出为方案: ${profileName}` })
      const res = await fetchProfiles()
      setProfiles(Array.isArray(res) ? res : [])
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '导出失败' })
    }
  }, [config])

  const handleImportProfile = useCallback(async (name: string) => {
    setMessage(null)
    try {
      const { fetchProfile } = await import('../api')
      const profile = await fetchProfile(name)
      setConfig(profile as unknown as Config)
      setMessage({ type: 'success', text: `已导入方案: ${name}` })
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '导入失败' })
    }
  }, [])

  const handleDeleteProfile = useCallback(async (name: string) => {
    try {
      await deleteProfile(name)
      setMessage({ type: 'success', text: `已删除方案: ${name}` })
      const res = await fetchProfiles()
      setProfiles(Array.isArray(res) ? res : [])
      setTimeout(() => setMessage(null), 3000)
    } catch (err) {
      setMessage({ type: 'error', text: err instanceof Error ? err.message : '删除失败' })
    }
  }, [])

  const updateModelField = useCallback(
    (target: 'primary' | 'fallback', field: string, value: string | number) => {
      setConfig((prev) => {
        const models = { ...prev.models }
        if (target === 'primary') {
          models.primary = { ...models.primary, [field]: value }
        } else {
          const fb = models.fallback || models.primary
          models.fallback = { ...fb, [field]: value }
        }
        return { ...prev, models }
      })
    },
    []
  )

  const updateExtraction = useCallback(
    (field: keyof ConfigExtraction, value: unknown) => {
      setConfig((prev) => ({
        ...prev,
        extraction: { ...prev.extraction, [field]: value },
      }))
    },
    []
  )

  const updatePriority = useCallback((key: PriorityKey, value: number) => {
    setConfig((prev) => ({
      ...prev,
      priorities: { weights: { ...prev.priorities.weights, [key]: value } },
    }))
  }, [])

  const updateConfidenceWeight = useCallback((key: keyof ConfidenceWeights, value: number) => {
    setConfig((prev) => ({
      ...prev,
      confidence: {
        ...prev.confidence,
        weights: { ...prev.confidence.weights, [key]: value },
      },
    }))
  }, [])

  const updateConfidenceThreshold = useCallback((value: number) => {
    setConfig((prev) => ({
      ...prev,
      confidence: { ...prev.confidence, threshold_review: value },
    }))
  }, [])

  const updateConcurrency = useCallback((field: keyof ConfigConcurrency, value: number) => {
    setConfig((prev) => ({
      ...prev,
      concurrency: { ...prev.concurrency, [field]: value },
    }))
  }, [])

  const updateOcr = useCallback((field: keyof ConfigOcr, value: boolean | string) => {
    setConfig((prev) => ({
      ...prev,
      ocr: { ...prev.ocr, [field]: value },
    }))
  }, [])

  const updateBudget = useCallback((field: keyof ConfigBudget, value: number | boolean) => {
    setConfig((prev) => ({
      ...prev,
      budget: { ...prev.budget, [field]: value },
    }))
  }, [])

  const updateStorage = useCallback((field: keyof ConfigStorage, value: string) => {
    setConfig((prev) => ({
      ...prev,
      storage: { ...prev.storage, [field]: value },
    }))
  }, [])

  const copyFromPrimary = useCallback(() => {
    setConfig((prev) => ({
      ...prev,
      models: {
        ...prev.models,
        fallback: { ...prev.models.primary },
      },
    }))
  }, [])

  const weights = config.confidence.weights
  const weightSum = weights.self + weights.consistency + weights.struct + weights.conflict

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent/30 border-t-accent" />
        <span className="ml-3 text-codex-text-muted">加载配置中...</span>
      </div>
    )
  }

  return (
    <div>
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-2xl text-codex-text-primary">
          <span className="inline-block pb-1 border-b-2 border-accent">系统配置</span>
        </h1>
        <div className="flex items-center gap-3">
          {message && (
            <span
              className={`text-sm font-medium ${
                message.type === 'success' ? 'text-emerald-400' : 'text-red-400'
              }`}
            >
              {message.text}
            </span>
          )}
          <button type="button" onClick={handleSave} disabled={saving} className="btn-primary">
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>
      </div>

      {/* ---- 模型配置 ---- */}
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
              className="input-field font-mono"
            />
          </div>
          <div>
            <Label htmlFor="primary-key">API Key</Label>
            <input
              id="primary-key"
              type="password"
              value={config.models.primary.api_key}
              onChange={(e) => updateModelField('primary', 'api_key', e.target.value)}
              className="input-field font-mono"
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
              className="input-field font-mono"
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
              className="input-field font-mono"
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
              className="input-field font-mono"
              min={1}
            />
          </div>
        </div>

        <div className="mt-4 pt-4 border-t border-codex-border">
          <label className="flex items-center gap-2 text-sm font-medium text-codex-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={!!config.models.fallback}
              onChange={(e) => {
                if (e.target.checked) {
                  copyFromPrimary()
                } else {
                  setConfig((prev) => ({
                    ...prev,
                    models: { ...prev.models, fallback: null },
                  }))
                }
              }}
              className={checkboxClasses}
            />
            启用备用模型
          </label>

          {config.models.fallback && (
            <div className="grid grid-cols-2 gap-4 mt-3 ml-6 p-4 bg-codex-bg-tertiary rounded-lg">
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
                  className="input-field font-mono"
                />
              </div>
              <div>
                <Label htmlFor="fallback-key">API Key</Label>
                <input
                  id="fallback-key"
                  type="password"
                  value={config.models.fallback.api_key}
                  onChange={(e) => updateModelField('fallback', 'api_key', e.target.value)}
                  className="input-field font-mono"
                />
              </div>
              <div>
                <Label htmlFor="fallback-base">Base URL</Label>
                <input
                  id="fallback-base"
                  type="text"
                  value={config.models.fallback.base_url}
                  onChange={(e) => updateModelField('fallback', 'base_url', e.target.value)}
                  className="input-field font-mono"
                />
              </div>
              <div>
                <Label htmlFor="fallback-rpm">RPM</Label>
                <input
                  id="fallback-rpm"
                  type="number"
                  value={config.models.fallback.rpm_limit}
                  onChange={(e) => updateModelField('fallback', 'rpm_limit', Number(e.target.value))}
                  className="input-field font-mono"
                />
              </div>
              <div>
                <Label htmlFor="fallback-tpm">TPM</Label>
                <input
                  id="fallback-tpm"
                  type="number"
                  value={config.models.fallback.tpm_limit}
                  onChange={(e) => updateModelField('fallback', 'tpm_limit', Number(e.target.value))}
                  className="input-field font-mono"
                />
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* ---- 抽取配置 ---- */}
      <CollapsibleSection title="抽取配置">
        <div className="space-y-4">
          <div>
            <Label>抽取粒度</Label>
            <div className="flex gap-6 mt-1">
              <label className="flex items-center gap-2 text-sm text-codex-text-secondary cursor-pointer">
                <input
                  type="radio"
                  name="granularity"
                  value="fine"
                  checked={config.extraction.granularity === 'fine'}
                  onChange={(e) => updateExtraction('granularity', e.target.value)}
                  className={radioClasses}
                />
                精细
              </label>
              <label className="flex items-center gap-2 text-sm text-codex-text-secondary cursor-pointer">
                <input
                  type="radio"
                  name="granularity"
                  value="balanced"
                  checked={config.extraction.granularity === 'balanced'}
                  onChange={(e) => updateExtraction('granularity', e.target.value)}
                  className={radioClasses}
                />
                平衡
              </label>
            </div>
          </div>

          <div>
            <Label>法规深度</Label>
            <div className="flex gap-6 mt-1">
              <label className="flex items-center gap-2 text-sm text-codex-text-secondary cursor-pointer">
                <input
                  type="radio"
                  name="regulation_depth"
                  value="full"
                  checked={config.extraction.regulation_depth === 'full'}
                  onChange={(e) => updateExtraction('regulation_depth', e.target.value)}
                  className={radioClasses}
                />
                完整条款
              </label>
              <label className="flex items-center gap-2 text-sm text-codex-text-secondary cursor-pointer">
                <input
                  type="radio"
                  name="regulation_depth"
                  value="limited"
                  checked={config.extraction.regulation_depth === 'limited'}
                  onChange={(e) => updateExtraction('regulation_depth', e.target.value)}
                  className={radioClasses}
                />
                摘要要点
              </label>
            </div>
          </div>

          <div>
            <Label htmlFor="industry-preset">行业预设</Label>
            <select
              id="industry-preset"
              value={config.extraction.industry_preset || ''}
              onChange={(e) => updateExtraction('industry_preset', e.target.value || null)}
              className="select-field"
            >
              <option value="">通用</option>
              <option value="金融">金融</option>
              <option value="医药">医药</option>
              <option value="IT">IT</option>
              <option value="建筑">建筑</option>
            </select>
          </div>

          <div>
            <Label htmlFor="industry-vocab">行业词汇 (每行一个)</Label>
            <textarea
              id="industry-vocab"
              value={config.extraction.industry_vocabulary}
              onChange={(e) => updateExtraction('industry_vocabulary', e.target.value)}
              rows={3}
              className="input-field"
              placeholder="供应链金融&#10;保理&#10;福费廷"
            />
          </div>

          <div>
            <Label htmlFor="focus-points">行业关注要点 (每行一个)</Label>
            <textarea
              id="focus-points"
              value={config.extraction.industry_focus_points}
              onChange={(e) => updateExtraction('industry_focus_points', e.target.value)}
              rows={3}
              className="input-field"
              placeholder="数据跨境传输合规&#10;个人信息保护&#10;反商业贿赂"
            />
          </div>

          <div>
            <Label>红线关键词</Label>
            <TagInput
              tags={config.extraction.redline_keywords}
              onChange={(tags) => updateExtraction('redline_keywords', tags)}
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* ---- 优先级配置 ---- */}
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
              className="flex items-center gap-4 py-2 px-3 bg-codex-bg-tertiary rounded-lg"
            >
              <span className="w-8 h-8 flex items-center justify-center rounded-full bg-accent text-codex-bg text-sm font-bold font-mono">
                {config.priorities.weights[item.key]}
              </span>
              <div className="flex-1">
                <div className="text-sm font-medium text-codex-text-primary">{item.label}</div>
                <div className="text-xs text-codex-text-muted">{item.desc}</div>
              </div>
              <input
                type="number"
                value={config.priorities.weights[item.key]}
                onChange={(e) => updatePriority(item.key, Number(e.target.value))}
                min={1}
                max={5}
                className="w-20 input-field text-center font-mono"
              />
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* ---- 置信度配置 ---- */}
      <CollapsibleSection title="置信度配置">
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <Label>人工复核阈值</Label>
              <span className="text-sm font-mono text-accent">
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
              className="w-full mt-1 accent-amber-500"
            />
            <div className="flex justify-between text-xs text-codex-text-muted font-mono">
              <span>0</span>
              <span>1</span>
            </div>
            <p className="text-xs text-codex-text-muted mt-1">
              低于此阈值的规则标记为"需人工复核"
            </p>
          </div>

          <div className="pt-3 border-t border-codex-border">
            <Label>权重分配 (必须总和为 1.0)</Label>
            <div className="grid grid-cols-4 gap-4 mt-1">
              {([
                { key: 'self' as keyof ConfidenceWeights, label: '自身置信度' },
                { key: 'consistency' as keyof ConfidenceWeights, label: '一致性' },
                { key: 'struct' as keyof ConfidenceWeights, label: '结构化' },
                { key: 'conflict' as keyof ConfidenceWeights, label: '冲突检测' },
              ]).map((w) => (
                <div key={w.key}>
                  <Label htmlFor={w.key}>{w.label}</Label>
                  <input
                    id={w.key}
                    type="number"
                    value={weights[w.key]}
                    onChange={(e) => updateConfidenceWeight(w.key, Number(e.target.value))}
                    min={0}
                    max={1}
                    step={0.01}
                    className="input-field font-mono"
                  />
                  <div className="mt-1 text-xs text-codex-text-muted font-mono">
                    {weights[w.key].toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-sm font-mono">
              <span
                className={
                  weightSum === 1
                    ? 'text-emerald-400'
                    : 'text-red-400 font-bold'
                }
              >
                当前总和: {weightSum.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* ---- 并发配置 ---- */}
      <CollapsibleSection title="并发配置">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="concur-files">最大并行文件数</Label>
            <input
              id="concur-files"
              type="number"
              value={config.concurrency.files}
              onChange={(e) => updateConcurrency('files', Number(e.target.value))}
              className="input-field font-mono"
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
              className="input-field font-mono"
              min={1}
              max={50}
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* ---- OCR 配置 ---- */}
      <CollapsibleSection title="OCR 配置">
        <div className="space-y-4">
          <Label>PDF OCR</Label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.ocr.enabled}
              onChange={(e) => updateOcr('enabled', e.target.checked)}
              className={checkboxClasses}
            />
            <span className="text-sm text-codex-text-secondary">
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

      {/* ---- 预算配置 ---- */}
      <CollapsibleSection title="预算配置">
        <div className="space-y-4">
          <div>
            <Label htmlFor="max-tokens">单批次最大 Token 数</Label>
            <input
              id="max-tokens"
              type="number"
              value={config.budget.max_tokens_per_batch}
              onChange={(e) => updateBudget('max_tokens_per_batch', Number(e.target.value))}
              className="input-field max-w-xs font-mono"
              min={10000}
              step={10000}
            />
          </div>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.budget.pause_on_overrun}
              onChange={(e) => updateBudget('pause_on_overrun', e.target.checked)}
              className={checkboxClasses}
            />
            <span className="text-sm text-codex-text-secondary">超出预算时暂停并等待确认</span>
          </label>
        </div>
      </CollapsibleSection>

      {/* ---- 存储配置 ---- */}
      <CollapsibleSection title="存储配置">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="db-path">数据库路径</Label>
            <input
              id="db-path"
              type="text"
              value={config.storage.db_path}
              onChange={(e) => updateStorage('db_path', e.target.value)}
              className="input-field font-mono"
            />
          </div>
          <div>
            <Label htmlFor="exports-dir">导出目录</Label>
            <input
              id="exports-dir"
              type="text"
              value={config.storage.exports_dir}
              onChange={(e) => updateStorage('exports_dir', e.target.value)}
              className="input-field font-mono"
            />
          </div>
        </div>
      </CollapsibleSection>

      {/* ---- 配置方案管理 ---- */}
      <div className="card p-5">
        <h3 className="text-base font-display text-codex-text-primary mb-4">配置方案管理</h3>

        <div className="flex gap-3 mb-4">
          <input
            type="text"
            value={newProfileName}
            onChange={(e) => setNewProfileName(e.target.value)}
            placeholder="方案名称"
            className="input-field max-w-xs"
          />
          <button
            type="button"
            onClick={() => {
              if (newProfileName.trim()) {
                handleExportProfile(newProfileName.trim())
                setNewProfileName('')
              }
            }}
            disabled={!newProfileName.trim()}
            className="btn-secondary"
          >
            导出当前配置
          </button>
        </div>

        {profiles.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium text-codex-text-secondary mb-2">已保存方案</div>
            {profiles.map((p) => (
              <div
                key={p.name}
                className="flex items-center justify-between py-2 px-3 bg-codex-bg-tertiary rounded-lg"
              >
                <div>
                  <div className="text-sm font-medium text-codex-text-primary">{p.name}</div>
                  {p.description && (
                    <div className="text-xs text-codex-text-muted">{p.description}</div>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleImportProfile(p.name)}
                    className="btn-secondary text-xs py-1 px-3"
                  >
                    加载
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteProfile(p.name)}
                    className="btn-danger text-xs py-1 px-3"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
