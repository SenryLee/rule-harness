import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Check,
  Combine,
  Download,
  Folder as FolderIcon,
  FolderPlus,
  Inbox,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import {
  createFolder,
  deleteFolder,
  deleteMerge,
  downloadMergeExport,
  fetchBatches,
  fetchFolderMerges,
  fetchFolders,
  mergeFolderBatches,
  patchBatch,
  renameFolder,
} from '../api';
import type { Batch, Folder, FolderMerge, MergeStats } from '../api';

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    running: '进行中', stopping: '停止中', cancelled: '已停止',
    success: '完成', partial: '部分完成', merged: '已入库', failed: '失败',
  };
  return map[status] || status;
}

export default function Archive() {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [activeFolder, setActiveFolder] = useState<Folder | null>(null);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');

  const loadFolders = () => {
    fetchFolders().then(setFolders).catch(() => {});
  };

  useEffect(() => { loadFolders(); }, []);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name || creating) return;
    setCreating(true);
    try {
      await createFolder(name);
      setNewName('');
      loadFolders();
    } catch {
      // ignore
    } finally {
      setCreating(false);
    }
  };

  const handleRename = async (folderId: string) => {
    const name = renameDraft.trim();
    if (name) {
      try {
        await renameFolder(folderId, name);
        loadFolders();
        if (activeFolder?.folder_id === folderId) {
          setActiveFolder((prev) => (prev ? { ...prev, name } : prev));
        }
      } catch {
        // ignore
      }
    }
    setRenamingId(null);
  };

  const handleDelete = async (folderId: string) => {
    try {
      await deleteFolder(folderId);
      if (activeFolder?.folder_id === folderId) setActiveFolder(null);
      loadFolders();
    } catch {
      // ignore
    }
  };

  if (activeFolder) {
    return (
      <FolderDetail
        folder={activeFolder}
        onBack={() => {
          setActiveFolder(null);
          loadFolders();
        }}
      />
    );
  }

  return (
    <div className="animate-page-in space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">项目归档</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            按企业/项目建文件夹归档任务；进入文件夹可发起新任务、合并多任务规则
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input-field w-52 py-2 text-sm"
            placeholder="新文件夹名，如：北京银行"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
          />
          <button className="btn-primary" disabled={!newName.trim() || creating} onClick={handleCreate}>
            <FolderPlus size={16} /> 创建
          </button>
        </div>
      </div>

      {folders.length === 0 ? (
        <div className="card px-6 py-16 text-center">
          <FolderIcon size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-[var(--text-muted)]">还没有归档文件夹，先创建一个吧</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {folders.map((folder) => (
            <div key={folder.folder_id} className="card card-hover group cursor-pointer p-5"
                 onClick={() => renamingId !== folder.folder_id && setActiveFolder(folder)}>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
                  <FolderIcon size={20} />
                </div>
                <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100"
                     onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn-ghost p-1.5"
                    title="重命名"
                    onClick={() => {
                      setRenamingId(folder.folder_id);
                      setRenameDraft(folder.name);
                    }}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    className="btn-ghost p-1.5 hover:text-[var(--color-red)]"
                    title="删除（任务会移回未归档）"
                    onClick={() => handleDelete(folder.folder_id)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {renamingId === folder.folder_id ? (
                <div className="mt-3 flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                  <input
                    autoFocus
                    className="input-field py-1 text-sm"
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRename(folder.folder_id);
                      if (e.key === 'Escape') setRenamingId(null);
                    }}
                  />
                  <button onClick={() => handleRename(folder.folder_id)} className="text-[var(--color-green)]"><Check size={15} /></button>
                  <button onClick={() => setRenamingId(null)} className="text-[var(--text-muted)]"><X size={15} /></button>
                </div>
              ) : (
                <p className="mt-3 truncate text-base font-semibold">{folder.name}</p>
              )}
              <p className="mt-1 text-xs text-[var(--text-muted)]">{folder.batch_count ?? 0} 个任务</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 文件夹详情：任务列表 + 合并规则 + 未归档移入 ─────────────────────

function FolderDetail({ folder, onBack }: { folder: Folder; onBack: () => void }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [unfiled, setUnfiled] = useState<Batch[]>([]);
  const [merges, setMerges] = useState<FolderMerge[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [merging, setMerging] = useState(false);
  const [mergeResult, setMergeResult] = useState<MergeStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showUnfiled, setShowUnfiled] = useState(false);

  const load = () => {
    fetchBatches(folder.folder_id).then(setBatches).catch(() => {});
    fetchBatches('').then(setUnfiled).catch(() => {});
    fetchFolderMerges(folder.folder_id).then(setMerges).catch(() => {});
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder.folder_id]);

  const toggleCheck = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleMerge = async () => {
    if (checked.size < 2 || merging) return;
    setMerging(true);
    setError(null);
    setMergeResult(null);
    try {
      const res = await mergeFolderBatches(folder.folder_id, [...checked]);
      setMergeResult(res.stats);
      setChecked(new Set());
      fetchFolderMerges(folder.folder_id).then(setMerges).catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : '合并失败');
    } finally {
      setMerging(false);
    }
  };

  const handleMoveIn = async (batchId: string) => {
    try {
      await patchBatch(batchId, { folder_id: folder.folder_id });
      load();
    } catch {
      // ignore
    }
  };

  const handleMoveOut = async (batchId: string) => {
    try {
      await patchBatch(batchId, { folder_id: '' });
      load();
    } catch {
      // ignore
    }
  };

  const handleDeleteMerge = async (mergeId: string) => {
    try {
      await deleteMerge(mergeId);
      setMerges((prev) => prev.filter((m) => m.merge_id !== mergeId));
    } catch {
      // ignore
    }
  };

  return (
    <div className="animate-page-in space-y-6">
      <div className="flex items-center gap-3">
        <button className="btn-ghost" onClick={onBack}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FolderIcon size={22} className="text-[var(--color-accent)]" /> {folder.name}
          </h1>
          <p className="mt-0.5 text-sm text-[var(--text-muted)]">
            {batches.length} 个任务 · 勾选 ≥2 个任务可合并去重
          </p>
        </div>
        <button
          className="btn-secondary"
          disabled={checked.size < 2 || merging}
          onClick={handleMerge}
        >
          <Combine size={16} /> {merging ? '合并中…' : `合并规则 (${checked.size})`}
        </button>
        <Link to={`/tasks/new?folder=${folder.folder_id}`} className="btn-primary">
          <Plus size={16} /> 在此新建任务
        </Link>
      </div>

      {error && (
        <div className="card border-[var(--color-red)] px-4 py-3 text-sm text-[var(--color-red)]">{error}</div>
      )}
      {mergeResult && (
        <div className="card px-5 py-4 text-sm">
          <p className="font-semibold text-[var(--color-green)]">合并完成</p>
          <p className="mt-1 text-[var(--text-secondary)]">
            {mergeResult.batches} 个任务共 {mergeResult.total_in} 条规则 → 去重后 {mergeResult.total_out} 条
            （指纹重复 -{mergeResult.fingerprint_dups_removed}，同口径近重复 -{mergeResult.struct_dups_removed}）。
            可在下方「合并存档」中下载。
          </p>
        </div>
      )}

      {/* 文件夹内任务 */}
      <div className="card overflow-hidden">
        <div className="border-b border-[var(--border-light)] px-5 py-3 text-sm font-medium">归档任务</div>
        {batches.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-[var(--text-muted)]">
            文件夹为空——新建任务会自动归档到这里，或从下方未归档任务移入
          </p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.batch_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)]">
                  <td className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      className="accent-[var(--color-accent)]"
                      checked={checked.has(batch.batch_id)}
                      onChange={() => toggleCheck(batch.batch_id)}
                      disabled={batch.status === 'running'}
                    />
                  </td>
                  <td className="max-w-[300px] px-2 py-3">
                    <Link to={`/tasks/${batch.batch_id}`} className="truncate font-medium hover:text-[var(--color-accent)] hover:underline">
                      {batch.name || batch.batch_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">{statusLabel(batch.status)}</td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                    {batch.stats?.total_rules ?? '—'} 条规则
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                    {batch.started_at?.slice(5, 16).replace('T', ' ')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-xs text-[var(--text-muted)] hover:text-[var(--color-red)]"
                      onClick={() => handleMoveOut(batch.batch_id)}
                    >
                      移出
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 合并存档 */}
      {merges.length > 0 && (
        <div className="card overflow-hidden">
          <div className="border-b border-[var(--border-light)] px-5 py-3 text-sm font-medium">合并存档</div>
          <table className="w-full text-sm">
            <tbody>
              {merges.map((merge) => (
                <tr key={merge.merge_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)]">
                  <td className="px-5 py-3 font-medium">{merge.name}</td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                    {merge.stats?.total_in ?? '—'} → {merge.stats?.total_out ?? '—'} 条
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                    {merge.created_at?.slice(5, 16).replace('T', ' ')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        className="btn-ghost px-2 py-1 text-xs"
                        onClick={() => downloadMergeExport(merge.merge_id, 'template')}
                      >
                        <Download size={13} /> 规则模板
                      </button>
                      <button
                        className="btn-ghost px-2 py-1 text-xs"
                        onClick={() => downloadMergeExport(merge.merge_id, 'located')}
                      >
                        <Download size={13} /> 含原文定位
                      </button>
                      <button
                        className="btn-ghost px-2 py-1 text-xs hover:text-[var(--color-red)]"
                        onClick={() => handleDeleteMerge(merge.merge_id)}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 未归档任务移入 */}
      <div className="card overflow-hidden">
        <button
          className="flex w-full items-center justify-between px-5 py-3 text-sm font-medium hover:bg-[var(--bg-hover)]"
          onClick={() => setShowUnfiled((v) => !v)}
        >
          <span className="inline-flex items-center gap-2">
            <Inbox size={15} /> 未归档任务（{unfiled.length}）
          </span>
          <span className="text-xs text-[var(--text-muted)]">{showUnfiled ? '收起' : '展开移入'}</span>
        </button>
        {showUnfiled && (
          unfiled.length === 0 ? (
            <p className="border-t border-[var(--border-light)] px-5 py-6 text-center text-sm text-[var(--text-muted)]">
              没有未归档的任务
            </p>
          ) : (
            <table className="w-full border-t border-[var(--border-light)] text-sm">
              <tbody>
                {unfiled.map((batch) => (
                  <tr key={batch.batch_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)]">
                    <td className="max-w-[300px] truncate px-5 py-3">{batch.name || batch.batch_id}</td>
                    <td className="px-4 py-3 text-xs text-[var(--text-muted)]">{statusLabel(batch.status)}</td>
                    <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                      {batch.started_at?.slice(5, 16).replace('T', ' ')}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        className="text-xs font-medium text-[var(--color-accent)] hover:underline"
                        onClick={() => handleMoveIn(batch.batch_id)}
                      >
                        移入此文件夹
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  );
}
