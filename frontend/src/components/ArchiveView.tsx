import { useCallback, useMemo, useState } from 'react';
import {
  archiveClassify,
  archiveConfirm,
  archiveUpdateClassification,
} from '../api';
import type { ArchiveFileClassification, ArchiveResult } from '../api';
import { Icon } from './Ui';

// ── Helpers ─────────────────────────────────────────────────────────

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.75) return 'text-emerald-600';
  if (confidence >= 0.5) return 'text-amber-600';
  return 'text-red-500';
}

function categoryIcon(dir: string): string {
  if (dir.startsWith('法律法规')) return '法';
  if (dir.startsWith('合同文本')) return '合';
  if (dir.startsWith('裁判文书')) return '裁';
  if (dir.startsWith('内部制度')) return '制';
  if (dir.startsWith('已有规则')) return '规';
  if (dir.startsWith('行业资料')) return '业';
  return '他';
}

function categoryColor(dir: string): string {
  if (dir.startsWith('法律法规')) return 'from-indigo-500 to-indigo-600';
  if (dir.startsWith('合同文本')) return 'from-blue-500 to-blue-600';
  if (dir.startsWith('裁判文书')) return 'from-purple-500 to-purple-600';
  if (dir.startsWith('内部制度')) return 'from-teal-500 to-teal-600';
  if (dir.startsWith('已有规则')) return 'from-emerald-500 to-emerald-600';
  if (dir.startsWith('行业资料')) return 'from-orange-500 to-orange-600';
  return 'from-gray-400 to-gray-500';
}

// ── Category selector ───────────────────────────────────────────────

const ALL_CATEGORIES = [
  '法律法规/国家法律',
  '法律法规/司法解释',
  '法律法规/部门规章',
  '法律法规/地方文件',
  '法律法规/司法问答',
  '裁判文书与案例/司法指引',
  '裁判文书与案例/案例',
  '合同文本/模板',
  '合同文本/历史合同',
  '合同文本/股权转让',
  '合同文本/通用合同',
  '内部制度/公司红线',
  '内部制度/管理制度',
  '内部制度/标准条款',
  '内部制度/业务规范',
  '已有规则/规则库',
  '已有规则/审查清单',
  '行业资料/特殊资料',
  '其他/未分类',
];

// ── Main component ──────────────────────────────────────────────────

type Phase = 'upload' | 'preview' | 'archiving' | 'done';

export default function ArchiveView() {
  const [phase, setPhase] = useState<Phase>('upload');
  const [dragging, setDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [useLlm, setUseLlm] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [classifications, setClassifications] = useState<ArchiveFileClassification[]>([]);
  const [categories, setCategories] = useState<Record<string, number>>({});
  const [archiving, setArchiving] = useState(false);
  const [archiveResult, setArchiveResult] = useState<ArchiveResult | null>(null);
  const [editingFile, setEditingFile] = useState<string | null>(null);

  // ── Upload ────────────────────────────────────────────────────────

  const addFiles = useCallback((incoming: FileList | File[]) => {
    setFiles((prev) => [...prev, ...Array.from(incoming)]);
  }, []);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer.files.length > 0) addFiles(event.dataTransfer.files);
    },
    [addFiles],
  );

  // ── Classify ──────────────────────────────────────────────────────

  const handleClassify = useCallback(async () => {
    if (files.length === 0) return;
    setClassifying(true);
    setClassifyError(null);
    try {
      const result = await archiveClassify(files, useLlm);
      setSessionId(result.session_id);
      setClassifications(result.files);
      setCategories(result.categories);
      setPhase('preview');
    } catch (err) {
      setClassifyError(err instanceof Error ? err.message : '分类失败');
    } finally {
      setClassifying(false);
    }
  }, [files, useLlm]);

  // ── Update classification ─────────────────────────────────────────

  const handleCategoryChange = useCallback(
    async (originalName: string, newCategory: string) => {
      if (!sessionId) return;
      try {
        const resp = await archiveUpdateClassification(sessionId, [
          { original_name: originalName, category_dir: newCategory },
        ]);
        setClassifications(resp.files);
        setEditingFile(null);
      } catch {
        // silently fail, user can retry
      }
    },
    [sessionId],
  );

  // ── Confirm archive ───────────────────────────────────────────────

  const handleConfirm = useCallback(async () => {
    if (!sessionId) return;
    setArchiving(true);
    setPhase('archiving');
    try {
      const result = await archiveConfirm(sessionId);
      setArchiveResult(result);
      setPhase('done');
    } catch (err) {
      setClassifyError(err instanceof Error ? err.message : '归档失败');
      setPhase('preview');
    } finally {
      setArchiving(false);
    }
  }, [sessionId]);

  // ── Reset ─────────────────────────────────────────────────────────

  const handleReset = useCallback(() => {
    setPhase('upload');
    setFiles([]);
    setSessionId(null);
    setClassifications([]);
    setCategories({});
    setArchiveResult(null);
    setClassifyError(null);
  }, []);

  // ── Stats ─────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const high = classifications.filter((f) => f.confidence >= 0.75).length;
    const mid = classifications.filter((f) => f.confidence >= 0.5 && f.confidence < 0.75).length;
    const low = classifications.filter((f) => f.confidence < 0.5).length;
    const llmCount = classifications.filter((f) => f.llm_enhanced).length;
    return { high, mid, low, llmCount };
  }, [classifications]);

  return (
    <div className="animate-fade-in max-w-6xl mx-auto space-y-5 pb-20">
      {/* Header */}
      <div>
        <h1 className="font-display text-2xl text-gray-900">文件归档</h1>
        <p className="text-sm text-gray-400 mt-1">
          上传法律文件，自动识别分类并整理到结构化目录中。
        </p>
      </div>

      {/* ═══ Phase: Upload ═══ */}
      {phase === 'upload' && (
        <>
          <section className="card p-5">
            <div
              onDrop={handleDrop}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              className={`border-2 border-dashed rounded-input p-10 text-center transition-all ${
                dragging ? 'border-primary bg-primary-soft' : 'border-air-border hover:border-air-border-accent'
              }`}
            >
              <input
                id="archive-upload"
                type="file"
                multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.tsv"
                className="hidden"
                onChange={(event) => {
                  if (event.target.files) addFiles(event.target.files);
                  event.currentTarget.value = '';
                }}
              />
              <label htmlFor="archive-upload" className="cursor-pointer">
                <div className="mx-auto w-12 h-12 rounded-xl bg-gradient-to-br from-[var(--primary)] to-blue-400 flex items-center justify-center text-white mb-3 shadow-md">
                  <Icon name="folder" size={24} />
                </div>
                <div className="text-base font-semibold text-gray-700">拖拽文件到这里进行智能归档</div>
                <div className="text-sm text-gray-400 mt-1">支持 Word / PDF / Excel / TXT / CSV，可同时上传多个文件</div>
              </label>
            </div>

            {files.length > 0 && (
              <div className="mt-5">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-sm font-semibold text-gray-900">
                    待归档文件
                    <span className="ml-2 badge-info">{files.length}</span>
                  </div>
                  <button type="button" onClick={() => setFiles([])} className="btn-ghost text-xs">
                    清空
                  </button>
                </div>
                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                  {files.map((file, index) => (
                    <div
                      key={`${file.name}-${index}`}
                      className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-[var(--bg-muted)] hover:bg-[var(--bg-hover)] transition-colors group"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-md bg-white border border-[var(--border)] flex items-center justify-center flex-shrink-0">
                          <Icon name="document" size={16} className="text-gray-400" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-gray-800 truncate">{file.name}</div>
                          <div className="text-[11px] text-gray-400">{formatSize(file.size)}</div>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFile(index)}
                        className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all p-1"
                      >
                        <Icon name="close" size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          {files.length > 0 && (
            <section className="card p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
              <label className="flex items-center gap-2.5 text-sm text-gray-600 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(e) => setUseLlm(e.target.checked)}
                  className="rounded border-gray-300 text-primary focus:ring-primary/30"
                />
                <Icon name="sparkles" size={16} className="text-amber-500" />
                <span>LLM 增强模式</span>
                <span className="text-xs text-gray-400">（对低置信文件用AI二次分类，更精准但需API调用）</span>
              </label>
              <button
                type="button"
                onClick={handleClassify}
                disabled={classifying}
                className="btn-primary text-sm"
              >
                {classifying ? (
                  <>
                    <span className="animate-spin inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
                    识别中...
                  </>
                ) : (
                  <>
                    <Icon name="search" size={16} />
                    开始智能分类
                  </>
                )}
              </button>
            </section>
          )}

          {classifyError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-card text-sm text-red-600">
              {classifyError}
            </div>
          )}
        </>
      )}

      {/* ═══ Phase: Preview ═══ */}
      {phase === 'preview' && (
        <>
          {/* Stats bar */}
          <section className="card p-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">{classifications.length}</div>
                <div className="text-xs text-gray-500 mt-0.5">总文件数</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-emerald-600">{stats.high}</div>
                <div className="text-xs text-gray-500 mt-0.5">高置信度</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-amber-600">{stats.mid + stats.low}</div>
                <div className="text-xs text-gray-500 mt-0.5">需确认</div>
              </div>
              {stats.llmCount > 0 && (
                <div className="text-center">
                  <div className="text-2xl font-bold text-purple-600">{stats.llmCount}</div>
                  <div className="text-xs text-gray-500 mt-0.5">AI 增强</div>
                </div>
              )}
            </div>
          </section>

          {/* Category summary */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">分类概览</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2.5">
              {Object.entries(categories).map(([cat, count]) => (
                <div
                  key={cat}
                  className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg border border-[var(--border)] bg-white hover:shadow-sm transition-shadow"
                >
                  <div className={`w-7 h-7 rounded-md bg-gradient-to-br ${categoryColor(cat)} text-white flex items-center justify-center text-xs font-bold flex-shrink-0`}>
                    {categoryIcon(cat)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-gray-700 truncate">{cat}</div>
                    <div className="text-[11px] text-gray-400">{count} 个文件</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* File list with editable categories */}
          <section className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-[var(--border)] flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900">分类详情</h2>
              <span className="text-xs text-gray-400">点击分类标签可手动调整</span>
            </div>
            <div className="divide-y divide-[var(--border-light)]">
              {classifications.map((file) => (
                <div key={file.original_name} className="px-5 py-3 hover:bg-[var(--bg-hover)] transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className={`w-8 h-8 rounded-md bg-gradient-to-br ${categoryColor(file.category_dir)} text-white flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5`}>
                        {categoryIcon(file.category_dir)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-gray-900 truncate">{file.original_name}</div>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          {editingFile === file.original_name ? (
                            <select
                              autoFocus
                              value={file.category_dir}
                              onChange={(e) => handleCategoryChange(file.original_name, e.target.value)}
                              onBlur={() => setEditingFile(null)}
                              className="text-xs border border-primary rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-primary/30"
                            >
                              {ALL_CATEGORIES.map((cat) => (
                                <option key={cat} value={cat}>{cat}</option>
                              ))}
                            </select>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setEditingFile(file.original_name)}
                              className="badge-info cursor-pointer hover:ring-2 hover:ring-blue-200 transition-all"
                            >
                              {file.category_dir}
                            </button>
                          )}
                          <span className="text-[11px] text-gray-400">{file.document_type}</span>
                          {file.llm_enhanced && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded-full">
                              <Icon name="sparkles" size={10} />
                              AI
                            </span>
                          )}
                        </div>
                        {file.evidence.length > 0 && (
                          <div className="text-[11px] text-gray-400 mt-1 truncate">
                            {file.evidence.slice(0, 2).join(' | ')}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end flex-shrink-0 gap-1">
                      <span className={`text-xs font-semibold ${confidenceColor(file.confidence)}`}>
                        {Math.round(file.confidence * 100)}%
                      </span>
                      <span className="text-[11px] text-gray-400">{formatSize(file.file_size)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Actions */}
          <section className="card p-5 flex items-center justify-between">
            <button type="button" onClick={handleReset} className="btn-secondary text-sm">
              重新选择文件
            </button>
            <button type="button" onClick={handleConfirm} disabled={archiving} className="btn-primary text-sm">
              <Icon name="check" size={16} />
              确认归档
            </button>
          </section>
        </>
      )}

      {/* ═══ Phase: Archiving ═══ */}
      {phase === 'archiving' && (
        <section className="card p-12 text-center">
          <div className="animate-spin mx-auto w-10 h-10 border-3 border-primary/20 border-t-primary rounded-full mb-4" />
          <div className="text-base font-semibold text-gray-700">正在归档文件...</div>
          <div className="text-sm text-gray-400 mt-1">正在创建目录结构并复制文件</div>
        </section>
      )}

      {/* ═══ Phase: Done ═══ */}
      {phase === 'done' && archiveResult && (
        <>
          {/* Success banner */}
          <section className="card p-5 bg-gradient-to-r from-emerald-50 to-teal-50 border-emerald-200">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-emerald-500 text-white flex items-center justify-center flex-shrink-0">
                <Icon name="check" size={22} />
              </div>
              <div>
                <div className="text-base font-semibold text-emerald-800">归档完成</div>
                <div className="text-sm text-emerald-600">
                  {archiveResult.total_files} 个文件已整理到 {Object.keys(archiveResult.directory_tree).length} 个分类目录
                </div>
              </div>
            </div>
          </section>

          {/* Directory tree */}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">归档目录结构</h2>
            <div className="space-y-3">
              {Object.entries(archiveResult.directory_tree).map(([dir, fileNames]) => (
                <div key={dir} className="rounded-lg border border-[var(--border)] overflow-hidden">
                  <div className="flex items-center gap-2.5 px-4 py-2.5 bg-[var(--bg-muted)]">
                    <div className={`w-6 h-6 rounded bg-gradient-to-br ${categoryColor(dir)} text-white flex items-center justify-center text-[10px] font-bold`}>
                      {categoryIcon(dir)}
                    </div>
                    <span className="text-sm font-medium text-gray-700">{dir}</span>
                    <span className="badge-gray ml-auto">{fileNames.length}</span>
                  </div>
                  <div className="px-4 py-2 space-y-1">
                    {fileNames.map((name) => (
                      <div key={name} className="flex items-center gap-2 text-sm text-gray-600 py-1">
                        <Icon name="document" size={14} className="text-gray-400 flex-shrink-0" />
                        <span className="truncate">{name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Action */}
          <section className="card p-5 flex justify-center">
            <button type="button" onClick={handleReset} className="btn-primary text-sm">
              <Icon name="plus" size={16} />
              开始新一轮归档
            </button>
          </section>
        </>
      )}
    </div>
  );
}
