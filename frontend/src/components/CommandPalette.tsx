import { useNavigate } from 'react-router-dom';
import { Plus, Settings, BookOpen, Zap, Search } from 'lucide-react';

interface CommandPaletteProps {
  onClose: () => void;
}

export default function CommandPalette({ onClose }: CommandPaletteProps) {
  const navigate = useNavigate();

  const actions = [
    {
      label: '新建任务',
      description: '创建新的规则抽取任务',
      icon: Plus,
      shortcut: '⌘N',
      run: () => { navigate('/tasks/new'); onClose(); },
    },
    {
      label: '规则库',
      description: '浏览和管理所有已抽取规则',
      icon: BookOpen,
      run: () => { navigate('/rules'); onClose(); },
    },
    {
      label: '任务中心',
      description: '查看历史批次和进度',
      icon: Zap,
      run: () => { navigate('/tasks'); onClose(); },
    },
    {
      label: '系统设置',
      description: '模型、参数和优先级配置',
      icon: Settings,
      run: () => { navigate('/settings'); onClose(); },
    },
  ];

  return (
    <div className="cmd-backdrop" onClick={onClose}>
      <div className="cmd-palette" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-[var(--border-light)] px-4 py-3">
          <Search size={16} className="text-[var(--text-muted)]" />
          <input
            autoFocus
            className="w-full bg-transparent text-sm outline-none placeholder:text-[var(--text-muted)]"
            placeholder="搜索命令或规则..."
          />
          <span className="kbd">ESC</span>
        </div>
        <div className="p-2">
          {actions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={action.run}
              className="flex w-full items-center gap-3 rounded-btn px-3 py-2.5 text-left transition-colors hover:bg-[var(--bg-hover)]"
            >
              <span className="flex h-8 w-8 items-center justify-center rounded-btn bg-[var(--color-blue-soft)] text-[var(--color-blue)]">
                <action.icon size={16} strokeWidth={1.8} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-[var(--text-primary)]">{action.label}</span>
                <span className="block truncate text-xs text-[var(--text-muted)]">{action.description}</span>
              </span>
              {action.shortcut && <span className="kbd">{action.shortcut}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
