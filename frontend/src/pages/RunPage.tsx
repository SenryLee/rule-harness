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

  let statusBadge = 'bg-gray-100 text-gray-800'
  if (progress?.status === 'completed') statusBadge = 'bg-green-100 text-green-800'
  else if (progress?.status === 'failed') statusBadge = 'bg-red-100 text-red-800'
  else if (progress?.status === 'partial') statusBadge = 'bg-yellow-100 text-yellow-800'
  else if (progress?.status === 'running') statusBadge = 'bg-blue-100 text-blue-800'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900">新建抽取任务</h1>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setStep('upload')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              step === 'upload' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-600'
            }`}
          >
            1. 上传文件
          </button>
          <button
            type="button"
            onClick={() => setStep('config')}
            disabled={!canProceed}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              step === 'config'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-200 text-gray-600 disabled:opacity-30'
            }`}
          >
            2. 批次配置
          </button>
          <button
            type="button"
            onClick={() => setStep('launch')}
            disabled={!canProceed}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              step === 'launch'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-200 text-gray-600 disabled:opacity-30'
            }`}
          >
            3. 启动
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
          <button type="button" onClick={() => setError(null)} className="ml-2 underline">
            关闭
          </button>
        </div>
      )}

      {step === 'upload' && (
        <div>
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`card border-dashed border-2 p-10 text-center cursor-pointer transition-colors ${
              dragging
                ? 'border-blue-400 bg-blue-50'
                : 'border-gray-300 hover:border-gray-400'
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
              <div className="text-gray-400 mb-3">
                <svg
                  className="mx-auto w-12 h-12"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
              </div>
              <p className="text-gray-600 font-medium">
                拖拽文件到此处，或点击选择文件
              </p>
              <p className="text-gray-400 text-sm mt-1">
                支持 PDF, Word, Excel, TXT, CSV
              </p>
            </label>
          </div>

          {files.length > 0 && (
            <div className="mt-6 space-y-3">
              {files.map((f) => (
                <div key={f.id} className="card p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3 flex-1">
                      <span className="badge-blue text-xs">{getFileIcon(f.file.name)}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-800 truncate">
                          {f.file.name}
                        </div>
                        <div className="text-xs text-gray-400">{formatSize(f.file.size)}</div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(f.id)}
                      className="text-gray-400 hover:text-red-500 ml-3"
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

                  <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">来源类别</label>
                      <select
                        value={f.meta.source_tag}
                        onChange={(e) => updateFileMeta(f.id, { source_tag: e.target.value })}
                        className="select-field text-xs"
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
                      <label className="block text-xs text-gray-500 mb-1">适用合同类型</label>
                      <div className="flex flex-wrap gap-1">
                        {['适用全部', ...CONTRACT_TYPES].map((ct) => {
                          const isAll = ct === '适用全部'
                          const checked = isAll
                            ? f.meta.contract_types.length === 0
                            : f.meta.contract_types.includes(ct)
                          return (
                            <label
                              key={ct}
                              className={`inline-flex items-center px-2 py-0.5 rounded text-xs cursor-pointer border ${
                                checked
                                  ? 'bg-blue-50 border-blue-300 text-blue-700'
                                  : 'bg-white border-gray-200 text-gray-600'
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
                        <label className="block text-xs text-gray-500 mb-1">扫描件</label>
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={f.meta.is_scanned}
                            onChange={(e) =>
                              updateFileMeta(f.id, { is_scanned: e.target.checked })
                            }
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          <span className="text-xs">PDF 扫描件</span>
                        </label>
                      </div>
                    )}

                    <div>
                      <label className="block text-xs text-gray-500 mb-1">适用法域</label>
                      <input
                        type="text"
                        value={f.meta.jurisdiction}
                        onChange={(e) => updateFileMeta(f.id, { jurisdiction: e.target.value })}
                        className="input-field text-xs"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-6 flex justify-between">
            <div className="text-sm text-gray-500">
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

      {step === 'config' && (
        <div>
          <div className="card p-6 space-y-4 max-w-xl">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                行业预设 (覆盖全局配置)
              </label>
              <select
                value={batchConfig.industry_preset}
                onChange={(e) =>
                  setBatchConfig((prev) => ({ ...prev, industry_preset: e.target.value }))
                }
                className="select-field"
              >
                {INDUSTRY_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                抽取粒度覆盖
              </label>
              <div className="flex gap-6">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="batch-granularity"
                    value="fine"
                    checked={batchConfig.granularity === 'fine'}
                    onChange={(e) =>
                      setBatchConfig((prev) => ({
                        ...prev,
                        granularity: e.target.value as 'fine' | 'balanced',
                      }))
                    }
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  精细
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="batch-granularity"
                    value="balanced"
                    checked={batchConfig.granularity === 'balanced'}
                    onChange={(e) =>
                      setBatchConfig((prev) => ({
                        ...prev,
                        granularity: e.target.value as 'fine' | 'balanced',
                      }))
                    }
                    className="text-blue-600 focus:ring-blue-500"
                  />
                  平衡
                </label>
              </div>
            </div>

            <div className="pt-4 border-t border-gray-200">
              <h4 className="text-sm font-medium text-gray-700 mb-2">Token 估算</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="text-sm text-gray-600">
                  文件总数: <span className="font-mono font-bold">{files.length}</span>
                </div>
                <div className="text-sm text-gray-600 mt-1">
                  预估 Token:{' '}
                  <span className="font-mono font-bold">
                    ~{(files.reduce((sum, f) => sum + f.file.size, 0) / 4).toLocaleString()}
                  </span>
                  <span className="text-xs text-gray-400 ml-1">(粗略估算,基于文件大小)</span>
                </div>
              </div>
            </div>
          </div>

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

      {step === 'launch' && (
        <div>
          {!currentBatchId ? (
            <div className="card p-8 text-center max-w-xl mx-auto">
              <h3 className="text-lg font-semibold text-gray-800 mb-2">确认启动</h3>
              <div className="text-sm text-gray-600 mb-6 space-y-1">
                <div>文件数量: {files.length}</div>
                <div>行业预设: {batchConfig.industry_preset || '通用'}</div>
                <div>抽取粒度: {batchConfig.granularity === 'fine' ? '精细' : '平衡'}</div>
              </div>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="btn-primary text-lg px-8 py-3"
              >
                {submitting ? '提交中...' : '开始抽取'}
              </button>
            </div>
          ) : (
            <div className="card p-6 max-w-2xl mx-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-gray-800">
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

              <div className="mb-4">
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>
                    {progress
                      ? `${progress.processed_files} / ${progress.total_files} 文件`
                      : '初始化...'}
                  </span>
                  <span>{progressPercent}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2.5">
                  <div
                    className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>

              {progress && (
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <div className="bg-gray-50 rounded-lg p-3 text-center">
                    <div className="text-xs text-gray-500">提取规则</div>
                    <div className="text-lg font-bold text-gray-800">
                      {progress.total_rules || '-'}
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 text-center">
                    <div className="text-xs text-gray-500">Token 消耗</div>
                    <div className="text-lg font-bold text-gray-800">
                      {progress.tokens_used
                        ? progress.tokens_used.toLocaleString()
                        : '-'}
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-3 text-center">
                    <div className="text-xs text-gray-500">错误数</div>
                    <div
                      className={`text-lg font-bold ${
                        progress.errors > 0 ? 'text-red-600' : 'text-gray-800'
                      }`}
                    >
                      {progress.errors}
                    </div>
                  </div>
                </div>
              )}

              {progress && (
                <div className="text-sm text-gray-500 mb-4">
                  当前步骤: {progress.current_step || '-'}
                </div>
              )}

              {progress &&
                (progress.status === 'completed' || progress.status === 'partial') && (
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => navigate(`/report/${currentBatchId}`)}
                      className="btn-primary"
                    >
                      查看报告
                    </button>
                  </div>
                )}

              {progress?.status === 'failed' && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
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
