import { useState, useCallback } from 'react';
import TaskPanel from './components/TaskPanel';
import RulesView from './components/RulesView';
import ConfigDrawer from './components/ConfigDrawer';

type ViewMode = 'rules' | 'batch';

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>('rules');
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleSelectBatch = useCallback((id: string | null) => {
    setSelectedBatchId(id);
    if (id) {
      setViewMode('batch');
    }
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const handleConfigSaved = useCallback(() => {
    setShowConfig(false);
    handleRefresh();
  }, [handleRefresh]);

  const handleNewTask = useCallback(() => {
    setSelectedBatchId(null);
    setViewMode('batch');
  }, []);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-air-muted">
      {/* ========== Header ========== */}
      <header className="h-14 flex-shrink-0 bg-white border-b border-air-border flex items-center justify-between px-4 z-10">
        {/* Left: Logo + title */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <svg
              className="w-6 h-6 text-primary"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
              />
            </svg>
            <h1 className="text-lg font-semibold text-gray-900 tracking-tight">
              规则梳理
            </h1>
          </div>
          {/* Blue dot accent */}
          <span className="w-2 h-2 rounded-full bg-primary inline-block" />
        </div>

        {/* Right: Action buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleNewTask}
            className="btn-primary text-sm"
          >
            <span className="flex items-center gap-1.5">
              <svg
                className="w-4 h-4"
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
              新建任务
            </span>
          </button>

          <button
            type="button"
            onClick={() => {
              setSelectedBatchId(null);
              setViewMode('rules');
            }}
            className={`btn-ghost text-sm ${
              viewMode === 'rules' && !selectedBatchId
                ? 'bg-primary-soft text-primary'
                : ''
            }`}
          >
            规则库
          </button>

          <button
            type="button"
            onClick={() => setShowConfig(true)}
            className="btn-ghost text-sm"
            title="系统配置"
          >
            <span className="flex items-center gap-1.5">
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
              配置
            </span>
          </button>
        </div>
      </header>

      {/* ========== Body ========== */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel: TaskPanel */}
        <aside className="w-80 flex-shrink-0 border-r border-air-border bg-white overflow-hidden">
          <TaskPanel
            selectedBatchId={selectedBatchId}
            onSelectBatch={handleSelectBatch}
            onRefresh={handleRefresh}
            refreshKey={refreshKey}
          />
        </aside>

        {/* Right Main Area: RulesView */}
        <main className="flex-1 overflow-y-auto bg-air-muted">
          <div className="p-6">
            <RulesView
              batchId={viewMode === 'batch' ? selectedBatchId : null}
              refreshKey={refreshKey}
            />
          </div>
        </main>
      </div>

      {/* ========== ConfigDrawer Overlay ========== */}
      {showConfig && (
        <ConfigDrawer
          onClose={() => setShowConfig(false)}
          onSaved={handleConfigSaved}
        />
      )}
    </div>
  );
}
