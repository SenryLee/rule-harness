import { useCallback, useMemo, useState } from 'react';
import TaskPanel from './components/TaskPanel';
import WorkbenchView from './components/WorkbenchView';
import ResultsView from './components/ResultsView';
import ConfigDrawer from './components/ConfigDrawer';
import type { Batch } from './api';

function isResultsStatus(status?: string): boolean {
  return status === 'success' || status === 'completed' || status === 'partial' || status === 'merged';
}

export default function App() {
  const [selectedBatch, setSelectedBatch] = useState<Batch | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

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

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-air-muted">
      <header className="h-14 flex-shrink-0 bg-white border-b border-air-border flex items-center justify-between px-4 z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <svg className="w-6 h-6 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
              />
            </svg>
            <h1 className="text-lg font-semibold text-gray-900 tracking-tight">规则梳理</h1>
          </div>
          <span className="w-2 h-2 rounded-full bg-primary inline-block" />
        </div>

        <div className="flex items-center gap-2">
          <button type="button" onClick={handleNewTask} className="btn-primary text-sm">
            + 新建任务
          </button>
          <button type="button" onClick={() => setShowConfig(true)} className="btn-ghost text-sm" title="系统配置">
            配置
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-80 flex-shrink-0 border-r border-air-border bg-white overflow-hidden">
          <TaskPanel
            selectedBatchId={selectedBatch?.batch_id || null}
            pendingNewTask={!selectedBatch}
            onSelectBatch={setSelectedBatch}
            refreshKey={refreshKey}
          />
        </aside>

        <main className="flex-1 overflow-y-auto bg-air-muted">
          <div className="p-6">
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
      </div>

      {showConfig && (
        <ConfigDrawer onClose={() => setShowConfig(false)} onSaved={handleConfigSaved} />
      )}
    </div>
  );
}
