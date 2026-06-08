import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  BookOpen,
  Zap,
  Link2,
  Settings,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/rules', icon: BookOpen, label: '规则库' },
  { to: '/tasks', icon: Zap, label: '任务中心' },
  { to: '/integrations', icon: Link2, label: 'Dify 集成' },
  { to: '/settings', icon: Settings, label: '系统设置' },
] as const;

export default function Sidebar() {
  return (
    <aside className="flex w-[220px] flex-shrink-0 flex-col border-r border-[var(--border-light)] bg-[var(--bg-surface)]">
      {/* Logo */}
      <div className="px-5 py-6">
        <h1 className="text-[17px] font-semibold tracking-tight text-[var(--text-primary)]">
          规则梳理
        </h1>
        <p className="mt-0.5 text-xs text-[var(--text-muted)]">Rule Extraction Platform</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3">
        <ul className="space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `nav-item ${isActive ? 'active' : ''}`
                }
              >
                <Icon size={18} strokeWidth={1.8} />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="border-t border-[var(--border-light)] px-5 py-4">
        <p className="text-[11px] text-[var(--text-muted)]">
          v2.0.0 · <span className="kbd">⌘K</span> 搜索
        </p>
      </div>
    </aside>
  );
}
