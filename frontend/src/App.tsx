import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import ArchiveView from './components/ArchiveView';
import TaskPanel from './components/TaskPanel';
import WorkbenchView from './components/WorkbenchView';
import ResultsView from './components/ResultsView';
import SettingsView from './components/SettingsView';
import { Icon } from './components/Ui';

function isResultsStatus(status?: string): boolean {
  return status === 'success' || status === 'completed' || status === 'partial' || status === 'merged';
}

function AppShell() {
  const { state, newTask, setView } = useApp();
  const { selectedBatch, currentView, refreshKey } = state;

  const [sidebarWidth, setSidebarWidth] = useState(272);
  const [isResizing, setIsResizing] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);

  const view = useMemo(
    () => {
      if (currentView === 'settings') return 'settings';
      if (currentView === 'archive') return 'archive';
      return isResultsStatus(selectedBatch?.status) ? 'results' : 'workbench';
    },
    [currentView, selectedBatch?.status],
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
        newTask();
      }
      if (event.key === 'Escape') {
        setCommandOpen(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [newTask]);

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg)] text-[var(--text-primary)]">
      <aside
        className="flex-shrink-0 overflow-hidden bg-[var(--bg-surface)]"
        style={{ width: sidebarWidth, transition: isResizing ? 'none' : 'width var(--dur-normal) var(--ease-out)' }}
      >
        <TaskPanel />
      </aside>

      <div
        className="resize-handle"
        onMouseDown={handleMouseDown}
        style={{ background: isResizing ? 'var(--primary-light)' : undefined }}
      />

      <main className="flex-1 overflow-y-auto">
        <div className="min-h-full px-5 py-6 md:px-8">
          {view === 'settings' ? (
            <SettingsView />
          ) : view === 'archive' ? (
            <ArchiveView />
          ) : view === 'results' && selectedBatch ? (
            <ResultsView batchId={selectedBatch.batch_id} refreshKey={refreshKey} />
          ) : (
            <WorkbenchView />
          )}
        </div>
      </main>

      {commandOpen && (
        <CommandPalette
          onClose={() => setCommandOpen(false)}
          onNewTask={() => {
            newTask();
            setCommandOpen(false);
          }}
          onOpenConfig={() => {
            setView('settings');
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
      run: onNewTask,
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

export default function App() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  );
}
