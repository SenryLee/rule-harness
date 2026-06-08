import { useCallback, useEffect, useState } from 'react';
import { Search, Filter, ChevronLeft, ChevronRight } from 'lucide-react';
import { fetchRules, toggleRuleEnabled } from '../api';
import type { RuleItem, RuleFilters } from '../api';

const RISK_OPTIONS = ['', '高', '中', '低'] as const;
const PAGE_SIZE = 20;

function riskBadge(level: string) {
  if (level === '高') return 'badge-danger';
  if (level === '中') return 'badge-warning';
  return 'badge-success';
}

export default function RuleLibrary() {
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const filters: RuleFilters = { page, page_size: PAGE_SIZE };
      if (search) filters.search = search;
      if (riskFilter) filters.risk_level = riskFilter;
      const res = await fetchRules(filters);
      setRules(res.rules);
      setTotal(res.total);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, search, riskFilter]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const handleToggle = async (rule: RuleItem) => {
    const enabled = rule.enabled === '启用' ? false : true;
    try {
      await toggleRuleEnabled(rule.rule_id, enabled);
      load();
    } catch {
      // ignore
    }
  };

  return (
    <div className="animate-page-in space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">规则库</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          跨批次浏览和管理所有已抽取规则 · 共 {total} 条
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className="input-field pl-9"
            placeholder="搜索检查项、审查要求..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-[var(--text-muted)]" />
          <select
            className="input-field w-auto min-w-[100px] appearance-none cursor-pointer"
            value={riskFilter}
            onChange={(e) => { setRiskFilter(e.target.value); setPage(1); }}
          >
            <option value="">全部风险</option>
            {RISK_OPTIONS.filter(Boolean).map((r) => (
              <option key={r} value={r}>{r}风险</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border-light)] text-left text-xs font-medium text-[var(--text-muted)]">
              <th className="px-5 py-3">风险</th>
              <th className="px-5 py-3">检查项</th>
              <th className="px-5 py-3">审查要求</th>
              <th className="px-5 py-3">主题</th>
              <th className="px-5 py-3">置信度</th>
              <th className="px-5 py-3">状态</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-5 py-12 text-center text-[var(--text-muted)]">加载中...</td></tr>
            ) : rules.length === 0 ? (
              <tr><td colSpan={6} className="px-5 py-12 text-center text-[var(--text-muted)]">暂无规则</td></tr>
            ) : (
              rules.map((rule) => (
                <tr key={rule.rule_id} className="border-b border-[var(--border-light)] last:border-0 hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-5 py-4">
                    <span className={riskBadge(rule.risk_level)}>{rule.risk_level}</span>
                  </td>
                  <td className="px-5 py-4 font-medium max-w-[240px] truncate">{rule.check_item}</td>
                  <td className="px-5 py-4 text-[var(--text-secondary)] max-w-[300px] truncate">{rule.requirement}</td>
                  <td className="px-5 py-4 text-xs text-[var(--text-muted)]">{rule.theme_key || '—'}</td>
                  <td className="px-5 py-4 font-mono text-xs">
                    {rule.combined_confidence != null ? (rule.combined_confidence * 100).toFixed(0) + '%' : '—'}
                  </td>
                  <td className="px-5 py-4">
                    <button
                      onClick={() => handleToggle(rule)}
                      className={`text-xs font-medium ${rule.enabled === '启用' ? 'text-[var(--color-green)]' : 'text-[var(--text-muted)]'}`}
                    >
                      {rule.enabled === '启用' ? '启用' : '停用'}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <p className="text-[var(--text-muted)]">
            第 {page} / {totalPages} 页
          </p>
          <div className="flex items-center gap-2">
            <button
              className="btn-ghost"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft size={16} /> 上一页
            </button>
            <button
              className="btn-ghost"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              下一页 <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
