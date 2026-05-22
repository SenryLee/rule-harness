import { Routes, Route, NavLink } from 'react-router-dom'
import ConfigPage from './pages/ConfigPage'
import RunPage from './pages/RunPage'
import ReportPage from './pages/ReportPage'
import RulesPage from './pages/RulesPage'
import BatchesPage from './pages/BatchesPage'

const navItems = [
  { to: '/config', label: '配置管理' },
  { to: '/run', label: '新建任务' },
  { to: '/batches', label: '历史任务' },
  { to: '/rules', label: '规则管理' },
]

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-slate-800 text-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex items-center h-14">
            <div className="flex-shrink-0 font-bold text-lg mr-8">
              规则梳理 Harness
            </div>
            <div className="flex space-x-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-slate-700 text-white'
                        : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<ConfigPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/run" element={<RunPage />} />
          <Route path="/report/:batchId" element={<ReportPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/batches" element={<BatchesPage />} />
        </Routes>
      </main>
    </div>
  )
}
