export interface ModelConfig {
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  rpm_limit: number;
  tpm_limit: number;
}

export interface ConfigModels {
  primary: ModelConfig;
  fallback: ModelConfig | null;
}

export interface ConfigExtraction {
  granularity: 'fine' | 'balanced';
  regulation_depth: 'full' | 'limited';
  consistency_sampling: boolean;
  industry_preset: string | null;
  industry_vocabulary: string;
  industry_focus_points: string;
  redline_keywords: string[];
}

export type PriorityKey = '法规' | '公司红线' | '内部制度' | '标准条款库' | '历史合同';

export interface ConfigPriorities {
  weights: Record<PriorityKey, number>;
}

export interface ConfidenceWeights {
  self: number;
  consistency: number;
  struct: number;
  conflict: number;
}

export interface ConfigConfidence {
  threshold_review: number;
  weights: ConfidenceWeights;
}

export interface ConfigConcurrency {
  files: number;
  blocks: number;
}

export interface ConfigOcr {
  enabled: boolean;
  engine: string;
  language: string;
}

export interface ConfigBudget {
  max_tokens_per_batch: number;
  pause_on_overrun: boolean;
}

export interface ConfigStorage {
  db_path: string;
  exports_dir: string;
}

export interface Config {
  models: ConfigModels;
  extraction: ConfigExtraction;
  priorities: ConfigPriorities;
  confidence: ConfigConfidence;
  concurrency: ConfigConcurrency;
  ocr: ConfigOcr;
  budget: ConfigBudget;
  storage: ConfigStorage;
}

export interface BatchStats {
  total_rules?: number;
  new_rules?: number;
  modified_rules?: number;
  conflicts?: number;
  high_risk?: number;
  medium_risk?: number;
  low_risk?: number;
  tokens_used?: number;
}

export interface Batch {
  batch_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  stats: BatchStats;
}

export interface BatchProgress {
  status: string;
  current_step: string;
  total_files: number;
  processed_files: number;
  total_blocks: number;
  processed_blocks: number;
  total_rules: number;
  tokens_used: number;
  errors: number;
}

export interface RuleItem {
  rule_id: string;
  enabled: boolean;
  risk_level: string;
  keywords: string[];
  check_item: string;
  requirement: string;
  notes: string;
  rule_type?: string;
  theme_key?: string;
  contract_types?: string[];
  version?: number;
  source_file?: string;
  source_filename?: string;
  pipeline?: string;
  confidence_self?: number;
  confidence_consistency?: number;
  confidence_struct?: number;
  confidence_conflict?: number;
  combined_confidence?: number;
  confidence?: number;
  variants?: unknown[];
  ladder_info?: unknown;
  cited_cases?: unknown[];
  conflict_flag?: string;
  batch_id?: string;
  source_excerpt?: string;
  source_location?: string;
  subject?: string;
  predicate?: string;
  threshold_type?: string;
  direction?: string;
  first_batch_id?: string;
  last_batch_id?: string;
  jurisdiction?: string;
  source_sha256?: string;
  model?: string;
  cited_cases_raw?: string[];
  struct_check_pass?: boolean;
  ladder_preferred?: string;
  ladder_acceptable?: string;
  ladder_unacceptable?: string;
}

export interface RuleListResponse {
  rules: RuleItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface Profile {
  name: string;
  label?: string;
  description: string;
}

export type ProfilesResponse = Profile[];

export interface ThemesResponse {
  keys: string[];
}

export interface PendingThemeMapping {
  rule_id: string;
  current_theme: string;
  suggested_theme: string;
}

export interface PendingThemesResponse {
  mappings: PendingThemeMapping[];
}

export interface ThemeApprovalRequest {
  mappings: Array<{ rule_id: string; approved_theme: string }>;
}

export interface RuleFilters {
  risk_level?: string;
  rule_type?: string;
  theme_key?: string;
  contract_type?: string;
  enabled?: boolean;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface BatchRuleFilters {
  risk_level?: string;
  pipeline?: string;
  confidence_min?: number;
  confidence_max?: number;
  conflict_flag?: string;
  contract_type?: string;
  source_file?: string;
  page?: number;
  page_size?: number;
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  try {
    const response = await fetch(url, options);

    if (!response.ok) {
      let message = `请求失败 (${response.status})`;
      try {
        const body = await response.json();
        if (body.detail) {
          message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
        } else if (body.message) {
          message = body.message;
        }
      } catch {
        message = `请求失败 (${response.status})`;
      }
      throw new ApiError(message, response.status);
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return response.json();
    }
    return undefined as unknown as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const message = error instanceof Error ? error.message : '网络请求失败';
    throw new ApiError(message, 0);
  }
}

function buildQueryString(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== ''
  );
  if (entries.length === 0) return '';
  return '?' + new URLSearchParams(
    entries.map(([k, v]) => [k, String(v)])
  ).toString();
}

export function fetchConfig(): Promise<Config> {
  return request<Config>('/api/config');
}

export function updateConfig(config: Config): Promise<void> {
  return request<void>('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function fetchProfiles(): Promise<ProfilesResponse> {
  return request<ProfilesResponse>('/api/profiles');
}

export function fetchProfile(name: string): Promise<Profile> {
  return request<Profile>(`/api/profiles/${encodeURIComponent(name)}`);
}

export function deleteProfile(name: string): Promise<void> {
  return request<void>(`/api/profiles/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export function saveProfile(name: string, config: Config): Promise<void> {
  return request<void>(`/api/profiles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export interface CreateBatchMeta {
  source_tag: string;
  contract_types: string[];
  is_scanned?: boolean;
  jurisdiction?: string;
}

export interface CreateBatchResponse {
  batch_id: string;
  status: string;
}

export function createBatch(files: File[], meta: CreateBatchMeta[]): Promise<CreateBatchResponse> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file);
  });
  formData.append('meta', JSON.stringify(meta));
  return request<CreateBatchResponse>('/api/batches', {
    method: 'POST',
    body: formData,
  });
}

export function fetchBatches(): Promise<Batch[]> {
  return request<Batch[]>('/api/batches');
}

export function fetchBatch(id: string): Promise<Batch> {
  return request<Batch>(`/api/batches/${encodeURIComponent(id)}`);
}

export function fetchBatchProgress(id: string): Promise<BatchProgress> {
  return request<BatchProgress>(`/api/batches/${encodeURIComponent(id)}/progress`);
}

export function fetchBatchRules(id: string, filters: BatchRuleFilters = {}): Promise<RuleListResponse> {
  const qs = buildQueryString(filters as Record<string, unknown>);
  return request<RuleListResponse>(`/api/batches/${encodeURIComponent(id)}/rules${qs}`);
}

export type ExportKind = 'main-csv' | 'metadata-csv' | 'conflict-report' | 'change-set';

export function downloadExport(id: string, kind: ExportKind): void {
  const url = `/api/batches/${encodeURIComponent(id)}/exports/${kind}`;
  window.open(url, '_blank');
}

export function applyMerge(id: string): Promise<void> {
  return request<void>(`/api/batches/${encodeURIComponent(id)}/apply`, {
    method: 'POST',
  });
}

export function deleteBatch(id: string): Promise<void> {
  return request<void>(`/api/batches/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function fetchRules(filters: RuleFilters = {}): Promise<RuleListResponse> {
  const qs = buildQueryString(filters as Record<string, unknown>);
  return request<RuleListResponse>(`/api/rules${qs}`);
}

export function toggleRuleEnabled(id: string, enabled: boolean): Promise<void> {
  return request<void>(`/api/rules/${encodeURIComponent(id)}/enabled`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
}

export function fetchThemes(): Promise<ThemesResponse> {
  return request<ThemesResponse>('/api/themes');
}

export function fetchPendingThemes(): Promise<PendingThemesResponse> {
  return request<PendingThemesResponse>('/api/themes/pending');
}

export function approveThemes(mappings: Array<{ rule_id: string; approved_theme: string }>): Promise<void> {
  return request<void>('/api/themes/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mappings }),
  });
}
