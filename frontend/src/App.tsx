import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import ConfigPage from './pages/ConfigPage'
import RunPage from './pages/RunPage'
import ReportPage from './pages/ReportPage'
import RulesPage from './pages/RulesPage'
import BatchesPage from './pages/BatchesPage'

const navItems = [
  { to: '/config', label: '系统配置', icon: IconConfig },
  { to: '/run', label: '新建任务', icon: IconRun },
  { to: '/batches', label: '历史任务', icon: IconBatches },
  { to: '/rules', label: '规则管理', icon: IconRules },
]

export default function App() {
  const location = useLocation()
  const isReport = location.pathname.startsWith('/report')

  return (
    <div className="flex h-screen overflow-hidden bg-codex-bg">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 bg-codex-bg border-r border-codex-border flex flex-col">
        {/* Brand */}
        <div className="h-16 flex items-center px-5 border-b border-codex-border">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
              <span className="font-display text-codex-bg text-lg font-bold">R</span>
            </div>
            <div>
              <div className="font-display text-codex-text-primary text-sm tracking-wide">
                规则梳理
              </div>
              <div className="text-codex-text-muted text-[10px] tracking-widest uppercase">
                Harness
              </div>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                isActive && !isReport ? 'sidebar-link-active' : 'sidebar-link'
              }
            >
              <item.icon />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-codex-border">
          <div className="text-[11px] text-codex-text-muted">
            v1.0.0 · Noir Codex
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Routes>
            <Route path="/" element={<ConfigPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/run" element={<RunPage />} />
            <Route path="/report/:batchId" element={<ReportPage />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/batches" element={<BatchesPage />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}

/* Simple SVG icons — tiny, no extra deps */
function IconConfig() {
  return (
    <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )
}

function IconRun() {
  return (
    <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
    </svg>
  )
}

function IconBatches() {
  return (
    <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  )
}

function IconRules() {
  return (
    <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
    </svg>
  )
}
