import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, FileText, X, ArrowRight, ArrowLeft } from 'lucide-react';
import { createBatch, previewClassify } from '../api';
import type { CreateBatchMeta, PreviewClassifyResponse } from '../api';

interface FileEntry {
  file: File;
  meta: CreateBatchMeta;
  preview?: PreviewClassifyResponse;
  classifying: boolean;
}

const STEPS = ['上传文件', '确认配置', '开始抽取'] as const;

export default function TaskNew() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [files, setFiles] = useState<FileEntry[]>([]);
  

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    addFiles(dropped);
  }, []);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
  };

  const addFiles = (newFiles: File[]) => {
    const entries: FileEntry[] = newFiles.map((file) => ({
      file,
      meta: { source_tag: '合同文本', contract_types: [] },
      classifying: true,
    }));
    setFiles((prev) => [...prev, ...entries]);

    // Auto-classify each
    entries.forEach((entry) => {
      previewClassify(entry.file)
        .then((result) => {
          setFiles((prev) => {
            const updated = [...prev];
            const target = updated.find((f) => f.file === entry.file);
            if (target) {
              target.preview = result;
              target.meta.source_tag = result.suggested_source_tag || target.meta.source_tag;
              target.meta.contract_types = result.suggested_contract_types || [];
              target.classifying = false;
            }
            return updated;
          });
        })
        .catch(() => {
          setFiles((prev) => {
            const updated = [...prev];
            const target = updated.find((f) => f.file === entry.file);
            if (target) target.classifying = false;
            return updated;
          });
        });
    });
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {

    try {
      const result = await createBatch(
        files.map((f) => f.file),
        files.map((f) => f.meta),
      );
      navigate(`/tasks/${result.batch_id}`);
    } catch {
      
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
            <div className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
              i <= step ? 'bg-[var(--color-blue)] text-white' : 'bg-[var(--color-gray-5)] text-[var(--text-muted)]'
            }`}>
              {i + 1}
            </div>
            <span className={`text-sm ${i <= step ? 'font-medium text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}>
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
            className="card flex flex-col items-center justify-center px-6 py-16 border-2 border-dashed border-[var(--border)] hover:border-[var(--color-blue)] transition-colors cursor-pointer"
            onClick={() => document.getElementById('file-input')?.click()}
          >
            <Upload size={32} className="text-[var(--text-muted)] mb-3" />
            <p className="text-sm font-medium">拖拽文件到此处，或点击选择</p>
            <p className="mt-1 text-xs text-[var(--text-muted)]">支持 PDF、DOCX、TXT 格式</p>
            <input
              id="file-input"
              type="file"
              multiple
              accept=".pdf,.docx,.doc,.txt,.md"
              className="hidden"
              onChange={handleFileInput}
            />
          </div>

          {files.length > 0 && (
            <div className="space-y-2">
              {files.map((entry, idx) => (
                <div key={idx} className="card flex items-center gap-3 px-4 py-3">
                  <FileText size={18} className="text-[var(--text-muted)] flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{entry.file.name}</p>
                    <p className="text-xs text-[var(--text-muted)]">
                      {(entry.file.size / 1024).toFixed(0)} KB
                      {entry.classifying && ' · 分类中...'}
                      {entry.preview && ` · ${entry.meta.source_tag}`}
                    </p>
                  </div>
                  <button onClick={() => removeFile(idx)} className="text-[var(--text-muted)] hover:text-[var(--color-red)]">
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-end">
            <button
              className="btn-primary"
              disabled={files.length === 0}
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
          <div className="card p-5 space-y-4">
            <h3 className="text-sm font-semibold">文件分类确认</h3>
            {files.map((entry, idx) => (
              <div key={idx} className="flex items-center gap-4 py-2 border-b border-[var(--border-light)] last:border-0">
                <p className="text-sm flex-1 truncate">{entry.file.name}</p>
                <select
                  className="input-field w-auto min-w-[140px]"
                  value={entry.meta.source_tag}
                  onChange={(e) => {
                    setFiles((prev) => {
                      const updated = [...prev];
                      updated[idx] = { ...updated[idx], meta: { ...updated[idx].meta, source_tag: e.target.value } };
                      return updated;
                    });
                  }}
                >
                  <option value="合同文本">合同文本</option>
                  <option value="法规">法规</option>
                  <option value="公司红线">公司红线</option>
                  <option value="内部制度">内部制度</option>
                  <option value="标准条款库">标准条款库</option>
                  <option value="历史合同">历史合同</option>
                </select>
                {entry.preview && (
                  <span className="text-xs text-[var(--text-muted)]">
                    置信度 {((entry.preview.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            ))}
          </div>

          <div className="flex justify-between">
            <button className="btn-secondary" onClick={() => setStep(0)}>
              <ArrowLeft size={16} /> 上一步
            </button>
            <button className="btn-primary" onClick={() => { setStep(2); handleSubmit(); }}>
              开始抽取 <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Submitting */}
      {step === 2 && (
        <div className="card px-6 py-16 text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-[var(--color-blue)] border-t-transparent" />
          <p className="mt-4 text-sm text-[var(--text-muted)]">正在创建任务并启动抽取...</p>
        </div>
      )}
    </div>
  );
}
