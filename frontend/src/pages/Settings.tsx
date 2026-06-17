import { useEffect, useState } from 'react';
import { Save, RefreshCw } from 'lucide-react';
import { fetchConfig, updateConfig } from '../api';
import type { Config } from '../api';

type Tab = 'model' | 'extraction' | 'priority' | 'confidence' | 'advanced';

const TABS: { key: Tab; label: string }[] = [
  { key: 'model', label: '模型' },
  { key: 'extraction', label: '抽取' },
  { key: 'priority', label: '优先级' },
  { key: 'confidence', label: '置信度' },
  { key: 'advanced', label: '高级' },
];

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null);
  const [tab, setTab] = useState<Tab>('model');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {});
  }, []);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      // 安全策略：前端不接触 API Key。保存时删除所有 api_key 字段，
      // 后端 _strip_all_api_keys 也会无条件剥离（双重保险）。
      const payload = JSON.parse(JSON.stringify(config));
      delete payload.models.primary.api_key;
      if (payload.models.fallback) delete payload.models.fallback.api_key;
      await updateConfig(payload as Config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  const updateField = (path: string, value: unknown) => {
    if (!config) return;
    const keys = path.split('.');
    const updated = JSON.parse(JSON.stringify(config));
    let obj = updated;
    for (let i = 0; i < keys.length - 1; i++) {
      obj = obj[keys[i]];
    }
    obj[keys[keys.length - 1]] = value;
    setConfig(updated);
  };

  if (!config) {
    return (
      <div className="animate-page-in">
        <div className="card px-6 py-12 text-center text-[var(--text-muted)]">加载配置中...</div>
      </div>
    );
  }

  return (
    <div className="animate-page-in space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">系统设置</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">模型、参数和优先级配置</p>
        </div>
        <button className="btn-primary" onClick={handleSave} disabled={saving}>
          {saved ? <><RefreshCw size={16} /> 已保存</> : <><Save size={16} /> 保存</>}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--border-light)]">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? 'border-[var(--color-blue)] text-[var(--color-blue)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="card p-6 space-y-5">
        {tab === 'model' && (
          <>
            <h3 className="text-sm font-semibold">主模型</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-[var(--text-muted)]">Provider</label>
                <input
                  className="input-field mt-1"
                  value={config.models.primary.provider}
                  onChange={(e) => updateField('models.primary.provider', e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">Model</label>
                <input
                  className="input-field mt-1"
                  value={config.models.primary.model}
                  onChange={(e) => updateField('models.primary.model', e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">Base URL</label>
                <input
                  className="input-field mt-1"
                  value={config.models.primary.base_url}
                  onChange={(e) => updateField('models.primary.base_url', e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">API Key</label>
                <div className="input-field mt-1 flex items-center justify-between bg-[var(--bg-secondary)] cursor-not-allowed">
                  <span className="text-sm text-[var(--text-muted)]">
                    {config.models.primary.api_key ? '由服务器环境变量管理' : '未配置（请联系运维设置环境变量）'}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-green)]/10 text-[var(--color-green)]">
                    已隔离
                  </span>
                </div>
              </div>
            </div>
          </>
        )}

        {tab === 'extraction' && (
          <>
            <h3 className="text-sm font-semibold">抽取参数</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-[var(--text-muted)]">
                  颗粒度：{config.extraction.granularity_level ?? 3} 档（1 粗 — 5 极细）
                </label>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  className="mt-1 w-full"
                  value={config.extraction.granularity_level ?? 3}
                  onChange={(e) => updateField('extraction.granularity_level', Number(e.target.value))}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">法规深度</label>
                <select
                  className="input-field mt-1"
                  value={config.extraction.regulation_depth}
                  onChange={(e) => updateField('extraction.regulation_depth', e.target.value)}
                >
                  <option value="full">完整</option>
                  <option value="limited">有限</option>
                </select>
              </div>
            </div>
          </>
        )}

        {tab === 'priority' && (
          <>
            <h3 className="text-sm font-semibold">源优先级权重</h3>
            <div className="space-y-3">
              {Object.entries(config.priorities.weights).map(([key, val]) => (
                <div key={key} className="flex items-center gap-4">
                  <span className="text-sm w-28">{key}</span>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={val}
                    onChange={(e) => updateField(`priorities.weights.${key}`, Number(e.target.value))}
                    className="flex-1"
                  />
                  <span className="text-sm font-mono w-6 text-right">{val}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'confidence' && (
          <>
            <h3 className="text-sm font-semibold">置信度配置</h3>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-[var(--text-muted)]">复核阈值</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  className="input-field mt-1 w-32"
                  value={config.confidence.threshold_review}
                  onChange={(e) => updateField('confidence.threshold_review', Number(e.target.value))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs text-[var(--text-muted)]">权重分配</label>
                {Object.entries(config.confidence.weights).map(([key, val]) => (
                  <div key={key} className="flex items-center gap-4">
                    <span className="text-sm w-28">{key}</span>
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      className="input-field w-24"
                      value={val}
                      onChange={(e) => updateField(`confidence.weights.${key}`, Number(e.target.value))}
                    />
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {tab === 'advanced' && (
          <>
            <h3 className="text-sm font-semibold">并发 & 预算</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-[var(--text-muted)]">文件并发数</label>
                <input
                  type="number"
                  className="input-field mt-1"
                  value={config.concurrency.files}
                  onChange={(e) => updateField('concurrency.files', Number(e.target.value))}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">块并发数</label>
                <input
                  type="number"
                  className="input-field mt-1"
                  value={config.concurrency.blocks}
                  onChange={(e) => updateField('concurrency.blocks', Number(e.target.value))}
                />
              </div>
              <div>
                <label className="text-xs text-[var(--text-muted)]">Token 预算</label>
                <input
                  type="number"
                  className="input-field mt-1"
                  value={config.budget.max_tokens_per_batch}
                  onChange={(e) => updateField('budget.max_tokens_per_batch', Number(e.target.value))}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
