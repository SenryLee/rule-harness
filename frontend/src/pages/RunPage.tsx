import { useState, useCallback, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { createBatch, fetchBatchProgress } from '../api'
import type { CreateBatchMeta } from '../api'

const SOURCE_CATEGORIES = [
  { value: '法规', label: '法规' },
  { value: '公司红线', label: '公司红线' },
  { value: '内部制度', label: '内部制度' },
  { value: '标准条款库', label: '标准条款库' },
  { value: '合同模板', label: '合同模板' },
  { value: '历史合同', label: '历史合同' },
  { value: '业务规范', label: '业务规范' },
  { value: '案例', label: '案例' },
  { value: '行业特殊', label: '行业特殊' },
  { value: '审查清单', label: '审查清单' },
]

const CONTRACT_TYPES = [
  '采购', '销售', '服务', '保密', '技术', '许可', '租赁', '劳动', '通用商事',
]

const INDUSTRY_PRESETS = [
  { value: '', label: '通用' },
  { value: 'finance', label: '金融' },
  { value: 'medical', label: '医疗' },
  { value: 'realestate', label: '房地产' },
  { value: 'ecommerce', label: '电商' },
  { value: 'manufacturing', label: '制造' },
  { value: 'energy', label: '能源' },
  { value: 'education', label: '教育' },
  { value: 'logistics', label: '物流' },
]

interface UploadedFile {
  id: string
  file: File
  meta: CreateBatchMeta
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return 'PDF'
  if (['doc', 'docx'].includes(ext)) return 'DOC'
  if (['xls', 'xlsx'].includes(ext)) return 'XLS'
  if (ext === 'txt') return 'TXT'
  return 'FILE'
}

type Step = 'upload' | 'config' | 'launch'

function StepIndicator({
  step,
  currentStep,
  index,
  label,
}: {
  step: Step
  currentStep: Step
  index: number
  label: string
}) {
  const steps: Step[] = ['upload', 'config', 'launch']
  const currentIdx = steps.indexOf(currentStep)
  const thisIdx = steps.indexOf(step)

  const isActive = currentStep === step
  const isCompleted = thisIdx < currentIdx

  return (
    <div className="flex flex-col items-center">
      <div
        className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all duration-300 ${
          isActive
            ? 'bg-accent text-codex-bg shadow-glow'
            : isCompleted
              ? 'bg-accent text-codex-bg'
              : 'border-2 border-codex-border text-codex-text-muted'
        }`}
      >
        {isCompleted ? (
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          index
        )}
      </div>
      <span
        className={`mt-2 text-xs font-medium transition-colors ${
          isActive
            ? 'text-accent'
            : isCompleted
              ? 'text-codex-text-secondary'
              : 'text-codex-text-muted'
        }`}
      >
        {label}
      </span>
    </div>
  )
}

function StepConnector({ filled }: { filled: boolean }) {
  return (
    <div className="flex-1 mx-2 mt-5">
      <div
        className={`h-0.5 rounded-full transition-colors ${
          filled ? 'bg-accent' : 'bg-codex-border'
        }`}
      />
    </div>
  )
}

export default function RunPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('upload')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [dragging, setDragging] = useState(false)
  const [batchConfig, setBatchConfig] = useState({
    industry_preset: '',
    granularity: 'balanced' as 'fine' | 'balanced',
  })
  const [submitting, setSubmitting] = useState(false)
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null)
  const [progress, setProgress] = useState<{
    status: string
    current_step: string
    total_files: number
    processed_files: number
    total_rules: number
    tokens_used: number
    errors: number
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  const idCounter = useRef(0)

  const addFiles = useCallback(
    (newFiles: FileList | File[]) => {
      const entries: UploadedFile[] = Array.from(newFiles).map((file) => {
        idCounter.current += 1
        return {
          id: String(idCounter.current),
          file,
          meta: {
            source_tag: '',
            contract_types: [],
            is_scanned: false,
            jurisdiction: '中国大陆',
          },
        }
      })
      setFiles((prev) => [...prev, ...entries])
    },
    []
  )

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }, [])

  const updateFileMeta = useCallback(
    (id: string, update: Partial<CreateBatchMeta>) => {
      setFiles((prev) =>
        prev.map((f) => (f.id === id ? { ...f, meta: { ...f.meta, ...update } } : f))
      )
    },
    []
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files)
      }
    },
    [addFiles]
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setDragging(false)
  }, [])

  const startPolling = useCallback((batchId: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current)
    pollingRef.current = setInterval(async () => {
      try {
        const prog = await fetchBatchProgress(batchId)
        setProgress(prog)
        if (prog.status === 'completed' || prog.status === 'failed' || prog.status === 'partial') {
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        }
      } catch {
        // polling silent failure
      }
    }, 2000)
  }, [])

  const handleSubmit = useCallback(async () => {
    setSubmitting(true)
    setError(null)
    try {
      const fileList = files.map((f) => f.file)
      const metaList = files.map((f) => f.meta)
      const result = await createBatch(fileList, metaList)
      setCurrentBatchId(result.batch_id)
      setStep('launch')
      startPolling(result.batch_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败')
    } finally {
      setSubmitting(false)
    }
  }, [files, startPolling])

  const canProceed = files.length > 0 && files.every((f) => f.meta.source_tag)

  const progressPercent = progress
    ? progress.total_files > 0
      ? Math.round((progress.processed_files / progress.total_files) * 100)
      : 0
    : 0

  let statusBadge = 'badge-info'
  if (progress?.status === 'completed') statusBadge = 'badge-success'
  else if (progress?.status === 'failed') statusBadge = 'badge-danger'
  else if (progress?.status === 'partial') statusBadge = 'badge-warning'
  else if (progress?.status === 'running') statusBadge = 'badge-accent'

  const steps: Step[] = ['upload', 'config', 'launch']

  return (
    <div className="font-body">
      {/* Page Title */}
      <div className="mb-8 pb-4 border-b-2 border-accent/30">
        <h1 className="font-display text-2xl text-codex-text-primary">新建抽取任务</h1>
        <p className="mt-1 text-sm text-codex-text-muted">
          上传法律文件，配置抽取参数，一键提取合规规则
        </p>
      </div>

      {/* Step Indicators */}
      <div className="flex items-center justify-center mb-8 px-4 max-w-lg mx-auto">
        {steps.map((s, idx) => (
          <StepIndicator
            key={s}
            step={s}
            currentStep={step}
            index={idx + 1}
            label={
              s === 'upload' ? '上传文件' : s === 'config' ? '批次配置' : '启动任务'
            }
          />
        ))}
        {steps.slice(0, -1).map((s, idx) => {
          const thisIdx = steps.indexOf(s)
          const currentIdx = steps.indexOf(step)
          return <StepConnector key={`conn-${idx}`} filled={thisIdx < currentIdx} />
        })}
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-6 p-4 bg-red-950/50 border border-red-800/50 rounded-card text-red-300 text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-red-400 hover:text-red-200 transition-colors ml-3"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* ─── Step 1: Upload ─── */}
      {step === 'upload' && (
        <div>
          {/* Drop Zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`border-2 border-dashed rounded-card p-12 text-center cursor-pointer transition-all duration-200 ${
              dragging
                ? 'border-accent/70 bg-accent-soft/10'
                : 'border-codex-border hover:border-accent/50 hover:bg-accent-soft/5'
            }`}
          >
            <input
              type="file"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files)
                e.target.value = ''
              }}
              className="hidden"
              id="file-upload"
            />
            <label htmlFor="file-upload" className="cursor-pointer">
              <div className="text-codex-text-muted mb-4">
                <svg
                  className="mx-auto w-14 h-14"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.2}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
              </div>
              <p className="text-codex-text-secondary text-base font-medium">
                拖拽文件到此处或点击上传
              </p>
              <p className="text-codex-text-muted text-sm mt-2">
                支持 PDF, Word, Excel, TXT, CSV
              </p>
            </label>
          </div>

          {/* File List */}
          {files.length > 0 && (
            <div className="mt-6 space-y-3">
              {files.map((f) => {
                const isSelected = f.meta.source_tag !== ''
                return (
                  <div
                    key={f.id}
                    className={`card p-4 border-l-4 transition-colors ${
                      isSelected
                        ? 'border-l-accent'
                        : 'border-l-transparent'
                    }`}
                  >
                    {/* File Header */}
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <span className="badge-accent text-xs font-mono flex-shrink-0">
                          {getFileIcon(f.file.name)}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-codex-text-primary truncate">
                            {f.file.name}
                          </div>
                          <div className="text-xs text-codex-text-muted mt-0.5">
                            {formatSize(f.file.size)}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFile(f.id)}
                        className="text-codex-text-muted hover:text-red-400 transition-colors ml-3 flex-shrink-0"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M6 18L18 6M6 6l12 12"
                          />
                        </svg>
                      </button>
                    </div>

                    {/* File Metadata Grid */}
                    <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div>
                        <label className="block text-xs text-codex-text-muted mb-1.5 font-medium">
                          来源类别
                        </label>
                        <select
                          value={f.meta.source_tag}
                          onChange={(e) =>
                            updateFileMeta(f.id, { source_tag: e.target.value })
                          }
                          className="select-field text-xs w-full"
                        >
                          <option value="">请选择</option>
                          {SOURCE_CATEGORIES.map((cat) => (
                            <option key={cat.value} value={cat.value}>
                              {cat.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-xs text-codex-text-muted mb-1.5 font-medium">
                          适用合同类型
                        </label>
                        <div className="flex flex-wrap gap-1.5">
                          {['适用全部', ...CONTRACT_TYPES].map((ct) => {
                            const isAll = ct === '适用全部'
                            const checked = isAll
                              ? f.meta.contract_types.length === 0
                              : f.meta.contract_types.includes(ct)
                            return (
                              <label
                                key={ct}
                                className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs cursor-pointer border transition-colors ${
                                  checked
                                    ? 'bg-accent-soft border-accent/50 text-accent'
                                    : 'bg-codex-bg-tertiary border-codex-border text-codex-text-muted hover:border-codex-text-muted'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => {
                                    if (isAll) {
                                      updateFileMeta(f.id, { contract_types: [] })
                                    } else {
                                      const current = f.meta.contract_types
                                      const updated = current.includes(ct)
                                        ? current.filter((c) => c !== ct)
                                        : [...current, ct]
                                      updateFileMeta(f.id, { contract_types: updated })
                                    }
                                  }}
                                  className="sr-only"
                                />
                                {ct}
                              </label>
                            )
                          })}
                        </div>
                      </div>

                      {f.file.name.toLowerCase().endsWith('.pdf') && (
                        <div>
                          <label className="block text-xs text-codex-text-muted mb-1.5 font-medium">
                            扫描件
                          </label>
                          <label className="inline-flex items-center gap-2.5 cursor-pointer">
                            <div className="relative">
                              <input
                                type="checkbox"
                                checked={f.meta.is_scanned}
                                onChange={(e) =>
                                  updateFileMeta(f.id, { is_scanned: e.target.checked })
                                }
                                className="sr-only peer"
                              />
                              <div className="w-9 h-5 bg-codex-bg-tertiary border border-codex-border rounded-full peer-checked:bg-accent peer-checked:border-accent transition-colors" />
                              <div className="absolute top-1 left-1 w-3 h-3 bg-codex-text-muted rounded-full peer-checked:translate-x-4 peer-checked:bg-codex-bg transition-transform" />
                            </div>
                            <span className="text-xs text-codex-text-secondary">
                              PDF 扫描件
                            </span>
                          </label>
                        </div>
                      )}

                      <div>
                        <label className="block text-xs text-codex-text-muted mb-1.5 font-medium">
                          适用法域
                        </label>
                        <input
                          type="text"
                          value={f.meta.jurisdiction}
                          onChange={(e) =>
                            updateFileMeta(f.id, { jurisdiction: e.target.value })
                          }
                          className="input-field text-xs w-full"
                        />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Bottom Bar */}
          <div className="mt-6 flex items-center justify-between">
            <div className="text-sm text-codex-text-muted">
              {files.length > 0
                ? `已选择 ${files.length} 个文件`
                : '尚未选择文件'}
            </div>
            <button
              type="button"
              onClick={() => setStep('config')}
              disabled={!canProceed}
              className="btn-primary"
            >
              下一步: 批次配置
            </button>
          </div>
        </div>
      )}

      {/* ─── Step 2: Config ─── */}
      {step === 'config' && (
        <div>
          <div className="card p-6 space-y-6 max-w-xl">
            {/* Industry Preset */}
            <div>
              <label className="block text-sm font-medium text-codex-text-primary mb-2">
                行业预设
                <span className="text-codex-text-muted text-xs font-normal ml-2">
                  覆盖全局配置
                </span>
              </label>
              <select
                value={batchConfig.industry_preset}
                onChange={(e) =>
                  setBatchConfig((prev) => ({ ...prev, industry_preset: e.target.value }))
                }
                className="select-field w-full"
              >
                {INDUSTRY_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Granularity Pill Toggle */}
            <div>
              <label className="block text-sm font-medium text-codex-text-primary mb-2">
                抽取粒度覆盖
              </label>
              <div className="inline-flex bg-codex-bg-tertiary rounded-card p-1 gap-1 border border-codex-border">
                {(['fine', 'balanced'] as const).map((g) => (
                  <button
                    key={g}
                    type="button"
                    onClick={() =>
                      setBatchConfig((prev) => ({
                        ...prev,
                        granularity: g,
                      }))
                    }
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                      batchConfig.granularity === g
                        ? 'bg-accent text-codex-bg shadow-sm'
                        : 'text-codex-text-muted hover:text-codex-text-secondary'
                    }`}
                  >
                    {g === 'fine' ? '精细' : '平衡'}
                  </button>
                ))}
              </div>
            </div>

            {/* Token Estimate */}
            <div className="pt-4 border-t border-codex-border">
              <h4 className="text-sm font-medium text-codex-text-primary mb-3">
                Token 估算
              </h4>
              <div className="bg-codex-bg-tertiary p-4 rounded-card space-y-2">
                <div className="text-sm text-codex-text-secondary flex justify-between">
                  <span>文件总数</span>
                  <span className="font-mono font-bold text-codex-text-primary">
                    {files.length}
                  </span>
                </div>
                <div className="text-sm text-codex-text-secondary flex justify-between">
                  <span>预估 Token</span>
                  <span className="font-mono font-bold text-codex-text-primary">
                    ~{(files.reduce((sum, f) => sum + f.file.size, 0) / 4).toLocaleString()}
                  </span>
                </div>
                <div className="text-xs text-codex-text-muted">
                  基于文件大小的粗略估算
                </div>
              </div>
            </div>
          </div>

          {/* Navigation Buttons */}
          <div className="mt-6 flex justify-between">
            <button type="button" onClick={() => setStep('upload')} className="btn-secondary">
              返回上传
            </button>
            <button
              type="button"
              onClick={() => setStep('launch')}
              disabled={!canProceed}
              className="btn-primary"
            >
              下一步: 启动任务
            </button>
          </div>
        </div>
      )}

      {/* ─── Step 3: Launch ─── */}
      {step === 'launch' && (
        <div>
          {!currentBatchId ? (
            /* Confirmation Card */
            <div className="card p-8 text-center max-w-xl mx-auto">
              <div className="text-accent mb-4">
                <svg className="mx-auto w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"
                  />
                </svg>
              </div>
              <h3 className="text-lg font-display font-semibold text-codex-text-primary mb-2">
                确认启动
              </h3>
              <div className="text-sm text-codex-text-secondary mb-6 space-y-1.5">
                <div>
                  <span className="text-codex-text-muted">文件数量: </span>
                  <span className="font-mono font-bold text-codex-text-primary">{files.length}</span>
                </div>
                <div>
                  <span className="text-codex-text-muted">行业预设: </span>
                  <span className="text-codex-text-primary">{batchConfig.industry_preset || '通用'}</span>
                </div>
                <div>
                  <span className="text-codex-text-muted">抽取粒度: </span>
                  <span className="text-codex-text-primary">
                    {batchConfig.granularity === 'fine' ? '精细' : '平衡'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="btn-primary text-lg px-10 py-3 inline-flex items-center gap-2"
              >
                {submitting ? (
                  <>
                    <svg
                      className="animate-spin w-5 h-5"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                    提交中...
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z"
                      />
                    </svg>
                    开始抽取
                  </>
                )}
              </button>
            </div>
          ) : (
            /* Progress Card */
            <div className="card p-6 max-w-2xl mx-auto">
              {/* Header */}
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-display font-semibold text-codex-text-primary">
                  任务运行中
                </h3>
                {progress && (
                  <span className={`badge ${statusBadge}`}>
                    {progress.status === 'completed'
                      ? '已完成'
                      : progress.status === 'running'
                        ? '运行中'
                        : progress.status === 'failed'
                          ? '失败'
                          : progress.status === 'partial'
                            ? '部分完成'
                            : progress.status}
                  </span>
                )}
              </div>

              {/* Progress Bar */}
              <div className="mb-6">
                <div className="flex justify-between text-xs text-codex-text-muted mb-2">
                  <span>
                    {progress
                      ? `${progress.processed_files} / ${progress.total_files} 文件`
                      : '初始化...'}
                  </span>
                  <span className="font-mono text-accent">{progressPercent}%</span>
                </div>
                <div className="w-full bg-codex-bg-tertiary rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-accent h-2.5 rounded-full transition-all duration-700 ease-out"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>

              {/* Stats Grid */}
              {progress && (
                <div className="grid grid-cols-4 gap-3 mb-6">
                  <div className="bg-codex-bg-tertiary rounded-card p-3 text-center border border-codex-border">
                    <div className="text-xs text-codex-text-muted mb-1">文件数</div>
                    <div className="text-lg font-mono font-bold text-codex-text-primary">
                      {progress.total_files || '-'}
                    </div>
                  </div>
                  <div className="bg-codex-bg-tertiary rounded-card p-3 text-center border border-codex-border">
                    <div className="text-xs text-codex-text-muted mb-1">提取规则</div>
                    <div className="text-lg font-mono font-bold text-codex-text-primary">
                      {progress.total_rules || '-'}
                    </div>
                  </div>
                  <div className="bg-codex-bg-tertiary rounded-card p-3 text-center border border-codex-border">
                    <div className="text-xs text-codex-text-muted mb-1">Token</div>
                    <div className="text-lg font-mono font-bold text-codex-text-primary">
                      {progress.tokens_used
                        ? progress.tokens_used.toLocaleString()
                        : '-'}
                    </div>
                  </div>
                  <div className="bg-codex-bg-tertiary rounded-card p-3 text-center border border-codex-border">
                    <div className="text-xs text-codex-text-muted mb-1">错误</div>
                    <div
                      className={`text-lg font-mono font-bold ${
                        progress.errors > 0 ? 'text-red-400' : 'text-codex-text-primary'
                      }`}
                    >
                      {progress.errors}
                    </div>
                  </div>
                </div>
              )}

              {/* Current Step */}
              {progress && (
                <div className="text-sm text-codex-text-secondary mb-4">
                  <span className="text-codex-text-muted">当前步骤: </span>
                  {progress.current_step || '-'}
                </div>
              )}

              {/* View Report Button */}
              {progress &&
                (progress.status === 'completed' || progress.status === 'partial') && (
                  <button
                    type="button"
                    onClick={() => navigate(`/report/${currentBatchId}`)}
                    className="btn-primary"
                  >
                    查看报告
                  </button>
                )}

              {/* Failed State */}
              {progress?.status === 'failed' && (
                <div className="p-4 bg-red-950/50 border border-red-800/50 rounded-card text-red-300 text-sm flex items-center gap-2">
                  <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  任务执行失败，请检查日志后重试。
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
