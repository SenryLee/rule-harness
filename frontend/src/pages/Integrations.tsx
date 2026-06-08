import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

const BASE_URL = window.location.origin;

const DIFY_CONFIG_EXAMPLE = `// Dify HTTP Request 节点配置
// ─────────────────────────────
// 1. 上传文件（触发抽取）
Method: POST
URL: ${BASE_URL}/api/dify/upload
Body Type: form-data
  files: {{文件变量}}
  source_tag: "dify"
  priority: 5

// 2. 轮询状态（循环节点）
Method: GET
URL: ${BASE_URL}/api/dify/batches/{{batch_id}}/status
// 退出条件: status !== "running"

// 3. 获取结果 JSON
Method: GET
URL: ${BASE_URL}/api/dify/batches/{{batch_id}}/rules.json`;

export default function Integrations() {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(DIFY_CONFIG_EXAMPLE);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="animate-page-in space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dify 集成</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          将本平台作为 Dify 工作流的规则抽取节点
        </p>
      </div>

      {/* Status */}
      <div className="card p-5">
        <div className="flex items-center gap-3">
          <div className="h-2.5 w-2.5 rounded-full bg-[var(--color-green)]" />
          <span className="text-sm font-medium">API 服务在线</span>
          <span className="text-xs text-[var(--text-muted)] ml-auto font-mono">{BASE_URL}</span>
        </div>
      </div>

      {/* Endpoints */}
      <section className="space-y-3">
        <h2 className="text-[17px] font-semibold">API Endpoints</h2>
        <div className="card divide-y divide-[var(--border-light)]">
          <div className="flex items-center gap-4 px-5 py-4">
            <span className="badge-info">POST</span>
            <code className="flex-1 text-xs font-mono">/api/dify/upload</code>
            <span className="text-xs text-[var(--text-muted)]">上传文件，创建批次</span>
          </div>
          <div className="flex items-center gap-4 px-5 py-4">
            <span className="badge-success">GET</span>
            <code className="flex-1 text-xs font-mono">/api/dify/batches/{'{batch_id}'}/status</code>
            <span className="text-xs text-[var(--text-muted)]">轮询批次状态</span>
          </div>
          <div className="flex items-center gap-4 px-5 py-4">
            <span className="badge-success">GET</span>
            <code className="flex-1 text-xs font-mono">/api/dify/batches/{'{batch_id}'}/rules.json</code>
            <span className="text-xs text-[var(--text-muted)]">下载规则 JSON</span>
          </div>
        </div>
      </section>

      {/* Config example */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[17px] font-semibold">Dify 工作流配置</h2>
          <button className="btn-ghost text-xs" onClick={handleCopy}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? '已复制' : '复制'}
          </button>
        </div>
        <div className="card p-5 overflow-x-auto">
          <pre className="text-xs font-mono text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
            {DIFY_CONFIG_EXAMPLE}
          </pre>
        </div>
      </section>

      {/* Architecture diagram */}
      <section className="space-y-3">
        <h2 className="text-[17px] font-semibold">集成架构</h2>
        <div className="card p-6">
          <div className="flex items-center justify-center gap-4 text-sm">
            <div className="rounded-btn bg-[var(--color-blue-soft)] px-4 py-2 text-[var(--color-blue)] font-medium">
              Dify 工作流
            </div>
            <span className="text-[var(--text-muted)]">→ 上传文件 →</span>
            <div className="rounded-btn bg-[var(--color-green-soft)] px-4 py-2 text-[var(--color-green)] font-medium">
              规则梳理平台
            </div>
            <span className="text-[var(--text-muted)]">→ JSON →</span>
            <div className="rounded-btn bg-[var(--color-blue-soft)] px-4 py-2 text-[var(--color-blue)] font-medium">
              Dify 下游节点
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
