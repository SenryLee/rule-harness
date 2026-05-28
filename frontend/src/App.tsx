import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import TaskPanel from './components/TaskPanel';
import WorkbenchView from './components/WorkbenchView';
import ResultsView from './components/ResultsView';
import ConfigDrawer from './components/ConfigDrawer';
import { Icon } from './components/Ui';
import type { Batch } from './api';

function isResultsStatus(status?: string): boolean {
  return status === 'success' || status === 'completed' || status === 'partial' || status === 'merged';
}

export default function App() {
  const [selectedBatch, setSelectedBatch] = useState<Batch | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [sidebarWidth, setSidebarWidth] = useState(272);
  const [isResizing, setIsResizing] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);

  const handleRefresh = useCallback(() => {
    setRefreshKey((key) => key + 1);
  }, []);

  const handleNewTask = useCallback(() => {
    setSelectedBatch(null);
  }, []);

  const handleConfigSaved = useCallback(() => {
    setShowConfig(false);
    handleRefresh();
  }, [handleRefresh]);

  const view = useMemo(
    () => (isResultsStatus(selectedBatch?.status) ? 'results' : 'workbench'),
    [selectedBatch?.status],
  );

  const handleMouseDown = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsResizing(true);
      const startX = event.clientX;
      const startWidth = sidebarWidth;

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const delta = moveEvent.clientX - startX;
        setSidebarWidth(Math.max(220, Math.min(420, startWidth + delta)));
      };

      const handleMouseUp = () => {
        setIsResizing(false);
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [sidebarWidth],
  );

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        handleNewTask();
      }
      if (event.key === 'Escape') {
        setCommandOpen(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [handleNewTask]);

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <aside
        className="flex-shrink-0 overflow-hidden bg-[var(--bg-surface)]"
        style={{ width: sidebarWidth, transition: isResizing ? 'none' : 'width var(--dur-normal) var(--ease-out)' }}
      >
        <TaskPanel
          selectedBatchId={selectedBatch?.batch_id || null}
          pendingNewTask={!selectedBatch}
          onSelectBatch={setSelectedBatch}
          onNewTask={handleNewTask}
          onOpenConfig={() => setShowConfig(true)}
          refreshKey={refreshKey}
        />
      </aside>

      <div
        className="resize-handle"
        onMouseDown={handleMouseDown}
        style={{ background: isResizing ? 'var(--primary-light)' : undefined }}
      />

      <main className="flex-1 overflow-y-auto">
        <div className="min-h-full px-5 py-6 md:px-8">
          {view === 'results' && selectedBatch ? (
            <ResultsView batchId={selectedBatch.batch_id} refreshKey={refreshKey} />
          ) : (
            <WorkbenchView
              selectedBatch={selectedBatch}
              onBatchUpdated={setSelectedBatch}
              onRefresh={handleRefresh}
            />
          )}
        </div>
      </main>

      {showConfig && (
        <ConfigDrawer onClose={() => setShowConfig(false)} onSaved={handleConfigSaved} />
      )}

      {commandOpen && (
        <CommandPalette
          onClose={() => setCommandOpen(false)}
          onNewTask={handleNewTask}
          onOpenConfig={() => {
            setShowConfig(true);
            setCommandOpen(false);
          }}
        />
      )}
    </div>
  );
}

function CommandPalette({
  onClose,
  onNewTask,
  onOpenConfig,
}: {
  onClose: () => void;
  onNewTask: () => void;
  onOpenConfig: () => void;
}) {
  const actions = [
    {
      label: '新建任务',
      description: '创建新的规则抽取任务',
      icon: 'plus',
      shortcut: '⌘N',
      run: () => {
        onNewTask();
        onClose();
      },
    },
    {
      label: '系统配置',
      description: '模型、行业预设、红线词和置信度配置',
      icon: 'settings',
      shortcut: '2',
      run: onOpenConfig,
    },
  ];

  return (
    <div className="cmd-backdrop" onClick={onClose}>
      <div className="cmd-palette" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3">
          <Icon name="search" size={18} className="text-[var(--text-muted)]" />
          <input
            autoFocus
            className="w-full bg-transparent text-sm outline-none placeholder:text-[var(--text-muted)]"
            placeholder="搜索命令..."
          />
          <span className="kbd">ESC</span>
        </div>
        <div className="p-2">
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={action.run}
              className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-[var(--bg-hover)]"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--primary-soft)] text-[var(--primary)]">
                <Icon name={action.icon} size={17} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-[var(--text-primary)]">{action.label}</span>
                <span className="block truncate text-xs text-[var(--text-muted)]">{action.description}</span>
              </span>
              <span className="kbd">{action.shortcut}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
