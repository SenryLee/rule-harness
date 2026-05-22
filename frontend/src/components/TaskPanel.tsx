import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchBatches,
  deleteBatch,
  createBatch,
  fetchBatchProgress,
} from '../api';
import type { Batch, CreateBatchMeta } from '../api';

/* ──────────────── Types ──────────────── */

interface TaskPanelProps {
  selectedBatchId: string | null;
  onSelectBatch: (id: string | null) => void;
  onRefresh: () => void;
  refreshKey: number;
}

interface UploadedFile {
  id: string;
  file: File;
  meta: CreateBatchMeta;
}

/* ──────────────── Constants ──────────────── */

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
];

const CONTRACT_TYPES = [
  '采购', '销售', '服务', '保密', '技术', '许可', '租赁', '劳动', '通用商事',
];

/* ──────────────── Helpers ──────────────── */

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '-';
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (ext === 'pdf') return 'PDF';
  if (['doc', 'docx'].includes(ext)) return 'DOC';
  if (['xls', 'xlsx'].includes(ext)) return 'XLS';
  if (ext === 'txt') return 'TXT';
  return 'FILE';
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { className: string; label: string }> = {
    completed: { className: 'badge-success', label: '已完成' },
    success: { className: 'badge-success', label: '成功' },
    partial: { className: 'badge-warning', label: '部分完成' },
    failed: { className: 'badge-danger', label: '失败' },
    running: { className: 'badge-info', label: '运行中' },
    pending: { className: 'badge-gray', label: '等待中' },
  };
  const config = map[status] || { className: 'badge-gray', label: status };
  return <span className={config.className}>{config.label}</span>;
}

/* ──────────────── Component ──────────────── */

export default function TaskPanel({
  selectedBatchId,
  onSelectBatch,
  onRefresh,
  refreshKey,
}: TaskPanelProps) {
  /* batch list state */
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(true);
  const [batchesError, setBatchesError] = useState<string | null>(null);

  /* upload section state */
  const [showUpload, setShowUpload] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    status: string;
    current_step: string;
    total_files: number;
    processed_files: number;
    total_rules: number;
    tokens_used: number;
    errors: number;
  } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const idCounter = useRef(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ─── Load batches ─── */
  const loadBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const data = await fetchBatches();
      setBatches(data);
      setBatchesError(null);
    } catch (err) {
      setBatchesError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches();
  }, [loadBatches, refreshKey]);

  /* ─── Cleanup polling on unmount ─── */
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  /* ─── File management ─── */
  const addFiles = useCallback((newFiles: FileList | File[]) => {
    const entries: UploadedFile[] = Array.from(newFiles).map((file) => {
      idCounter.current += 1;
      return {
        id: String(idCounter.current),
        file,
        meta: {
          source_tag: '',
          contract_types: [],
          is_scanned: false,
          jurisdiction: '中国大陆',
        },
      };
    });
    setFiles((prev) => [...prev, ...entries]);
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const updateFileMeta = useCallback(
    (id: string, update: Partial<CreateBatchMeta>) => {
      setFiles((prev) =>
        prev.map((f) => (f.id === id ? { ...f, meta: { ...f.meta, ...update } } : f)),
      );
    },
    [],
  );

  /* ─── Drag and drop ─── */
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragging(false);
  }, []);

  /* ─── Polling ─── */
  const startPolling = useCallback((batchId: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      try {
        const prog = await fetchBatchProgress(batchId);
        setProgress(prog);
        if (
          prog.status === 'completed' ||
          prog.status === 'failed' ||
          prog.status === 'partial'
        ) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          loadBatches();
          onRefresh();
        }
      } catch {
        // silent polling failure
      }
    }, 2000);
  }, [loadBatches, onRefresh]);

  /* ─── Submit batch ─── */
  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const fileList = files.map((f) => f.file);
      const metaList = files.map((f) => f.meta);
      const result = await createBatch(fileList, metaList);
      setCurrentBatchId(result.batch_id);
      startPolling(result.batch_id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  }, [files, startPolling]);

  /* ─── Delete batch ─── */
  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm('确认删除该批次？此操作不可撤销。')) return;
      try {
        await deleteBatch(id);
        if (selectedBatchId === id) {
          onSelectBatch(null);
        }
        setBatches((prev) => prev.filter((b) => b.batch_id !== id));
      } catch (err) {
        alert(err instanceof Error ? err.message : '删除失败');
      }
    },
    [selectedBatchId, onSelectBatch],
  );

  /* ─── Derived ─── */
  const canProceed = files.length > 0 && files.every((f) => f.meta.source_tag);
  const progressPercent = progress
    ? progress.total_files > 0
      ? Math.round((progress.processed_files / progress.total_files) * 100)
      : 0
    : 0;

  /* ─── Render ─── */
  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-air-border flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">任务列表</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadBatches}
            className="btn-ghost text-xs py-1 px-2"
            title="刷新"
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"
              />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => {
              setShowUpload(!showUpload);
              setCurrentBatchId(null);
              setProgress(null);
              setSubmitError(null);
            }}
            className={`btn-ghost text-xs py-1 px-2 ${
              showUpload ? 'bg-primary-soft text-primary' : ''
            }`}
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 4.5v15m7.5-7.5h-15"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Upload section (collapsible) */}
      {showUpload && (
        <div className="border-b border-air-border bg-air-muted">
          <div className="p-3">
            {/* Drag/drop zone */}
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              className={`border-2 border-dashed rounded-input p-4 text-center cursor-pointer transition-all ${
                dragging
                  ? 'border-primary bg-primary-soft'
                  : 'border-air-border hover:border-air-border-accent hover:bg-white'
              }`}
            >
              <input
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv"
                onChange={(e) => {
                  if (e.target.files) addFiles(e.target.files);
                  e.target.value = '';
                }}
                className="hidden"
                id="task-upload-input"
              />
              <label htmlFor="task-upload-input" className="cursor-pointer block">
                <svg
                  className="mx-auto w-8 h-8 text-gray-400 mb-1"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
                <p className="text-xs text-gray-500">拖拽文件或点击上传</p>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  PDF, Word, Excel, TXT, CSV
                </p>
              </label>
            </div>

            {/* File progress bar */}
            {currentBatchId && progress && (
              <div className="mt-3 p-3 bg-white rounded-card border border-air-border">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-gray-700">
                    {progress.status === 'running' ? '处理中...' : progress.status}
                  </span>
                  <span className="text-xs font-mono text-primary">{progressPercent}%</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-primary h-1.5 rounded-full transition-all duration-700"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
                <div className="flex justify-between mt-1.5 text-[10px] text-gray-400">
                  <span>
                    {progress.processed_files}/{progress.total_files} 文件
                  </span>
                  <span>{progress.total_rules || 0} 规则</span>
                </div>
              </div>
            )}

            {/* Submit error */}
            {submitError && (
              <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded-input text-red-600 text-xs">
                {submitError}
              </div>
            )}

            {/* File list */}
            {files.length > 0 && (
              <div className="mt-3 space-y-2 max-h-48 overflow-y-auto">
                {files.map((f) => (
                  <div
                    key={f.id}
                    className="bg-white rounded-input border border-air-border p-2"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <span className="badge-accent text-[10px] px-1.5 py-0 flex-shrink-0">
                          {getFileIcon(f.file.name)}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-xs text-gray-700 truncate">{f.file.name}</div>
                          <div className="text-[10px] text-gray-400">
                            {formatSize(f.file.size)}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFile(f.id)}
                        className="text-gray-400 hover:text-red-500 transition-colors ml-1 flex-shrink-0"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>

                    {/* Meta: source tag */}
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[10px] text-gray-400 mb-0.5">来源</label>
                        <select
                          value={f.meta.source_tag}
                          onChange={(e) => updateFileMeta(f.id, { source_tag: e.target.value })}
                          className="select-field text-[10px] py-1 px-1.5"
                        >
                          <option value="">选择</option>
                          {SOURCE_CATEGORIES.map((cat) => (
                            <option key={cat.value} value={cat.value}>
                              {cat.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-[10px] text-gray-400 mb-0.5">法域</label>
                        <input
                          type="text"
                          value={f.meta.jurisdiction}
                          onChange={(e) => updateFileMeta(f.id, { jurisdiction: e.target.value })}
                          className="input-field text-[10px] py-1 px-1.5"
                        />
                      </div>
                    </div>

                    {/* Contract types */}
                    <div className="mt-1.5">
                      <div className="flex flex-wrap gap-1">
                        {['全部', ...CONTRACT_TYPES].map((ct) => {
                          const isAll = ct === '全部';
                          const checked = isAll
                            ? f.meta.contract_types.length === 0
                            : f.meta.contract_types.includes(ct);
                          return (
                            <label
                              key={ct}
                              className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] cursor-pointer border transition-colors ${
                                checked
                                  ? 'bg-primary-soft border-primary/30 text-primary'
                                  : 'bg-white border-air-border text-gray-400 hover:border-gray-300'
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => {
                                  if (isAll) {
                                    updateFileMeta(f.id, { contract_types: [] });
                                  } else {
                                    const current = f.meta.contract_types;
                                    const updated = current.includes(ct)
                                      ? current.filter((c) => c !== ct)
                                      : [...current, ct];
                                    updateFileMeta(f.id, { contract_types: updated });
                                  }
                                }}
                                className="sr-only"
                              />
                              {ct}
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Submit button */}
            {files.length > 0 && !currentBatchId && (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canProceed || submitting}
                className="btn-primary text-sm w-full mt-3"
              >
                {submitting ? '提交中...' : '开始抽取'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Batch list */}
      <div className="flex-1 overflow-y-auto">
        {batchesLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary/20 border-t-primary" />
            <span className="ml-2 text-xs text-gray-400">加载中...</span>
          </div>
        ) : batchesError ? (
          <div className="px-4 py-4">
            <div className="p-3 bg-red-50 border border-red-200 rounded-card text-red-600 text-xs">
              {batchesError}
            </div>
            <button type="button" onClick={loadBatches} className="btn-secondary text-xs mt-2 w-full">
              重试
            </button>
          </div>
        ) : batches.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <svg
              className="mx-auto w-10 h-10 text-gray-300 mb-2"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z"
              />
            </svg>
            <p className="text-xs text-gray-400">暂无历史任务</p>
            <button
              type="button"
              onClick={() => setShowUpload(true)}
              className="btn-primary text-xs mt-3"
            >
              新建任务
            </button>
          </div>
        ) : (
          <div className="divide-y divide-air-border">
            {batches.map((batch) => {
              const isSelected = selectedBatchId === batch.batch_id;
              const stats = batch.stats || {};
              return (
                <button
                  key={batch.batch_id}
                  type="button"
                  onClick={() => onSelectBatch(isSelected ? null : batch.batch_id)}
                  className={`w-full text-left px-4 py-3 transition-colors hover:bg-air-hover ${
                    isSelected
                      ? 'bg-primary-soft border-l-[3px] border-l-primary'
                      : 'border-l-[3px] border-l-transparent'
                  }`}
                >
                  {/* Top row: status + date */}
                  <div className="flex items-center justify-between mb-1">
                    <StatusBadge status={batch.status} />
                    <span className="text-[10px] text-gray-400">
                      {formatDate(batch.started_at)}
                    </span>
                  </div>

                  {/* Batch ID */}
                  <div className="text-xs font-mono text-gray-500 truncate mb-1">
                    {batch.batch_id}
                  </div>

                  {/* Stats summary */}
                  <div className="flex items-center gap-2 text-[10px] text-gray-400">
                    {stats.total_rules != null && (
                      <span>{stats.total_rules} 条规则</span>
                    )}
                    {stats.high_risk != null && stats.high_risk > 0 && (
                      <span className="text-red-500">{stats.high_risk} 高风险</span>
                    )}
                    {stats.tokens_used != null && (
                      <span>{(stats.tokens_used / 1000).toFixed(0)}K tokens</span>
                    )}
                  </div>

                  {/* Actions */}
                  {isSelected && (
                    <div className="mt-2 flex gap-1 border-t border-air-border pt-2">
                      {(batch.status === 'completed' || batch.status === 'partial') && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRefresh();
                          }}
                          className="btn-ghost text-[10px] py-1 px-2"
                        >
                          查看规则
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(batch.batch_id);
                        }}
                        className="btn-ghost text-[10px] py-1 px-2 text-red-500 hover:text-red-600"
                      >
                        删除
                      </button>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
