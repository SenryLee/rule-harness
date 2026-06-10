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
  /** v1.2: 颗粒度档位 1(粗)–5(极细)，驱动切块/拆分/跳过门槛/去重/密度提示 */
  granularity_level?: number;
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
  /** v1.1: 数值忠实度门权重。后端默认返回 0.30。老配置可缺。 */
  fidelity?: number;
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
  total_files?: number;
  file_metas?: CreateBatchMeta[];
  summary?: BatchStats;
}

export interface PipelineFileState {
  filename: string;
  status: 'pending' | 'running' | 'done' | 'skipped' | 'failed';
  blocks_total: number;
  blocks_done: number;
  rules_emitted: number;
  skip_reason?: string | null;
}

export interface PipelineState {
  label: string;
  status: 'pending' | 'running' | 'done' | 'skipped' | 'failed';
  files_total: number;
  files_done: number;
  blocks_total: number;
  blocks_done: number;
  rules_emitted: number;
  skip_reason?: string | null;
  files?: Record<string, PipelineFileState>;
}

export interface FidelityStats {
  intercepted: number;
  placeholders: number;
  discarded: number;
  voice_mismatch: number;
}

export interface BatchProgress {
  status: string;
  cancel_requested?: boolean;
  current_step: string;
  total_files: number;
  processed_files: number;
  total_blocks: number;
  processed_blocks: number;
  total_rules: number;
  tokens_used: number;
  errors: string[];
  pipeline_progress?: Record<string, PipelineState>;
  fidelity_stats?: FidelityStats;
}

export interface RuleItem {
  rule_id: string;
  enabled: string | boolean;
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
  source_tag?: string;
  pipeline?: string;
  self_confidence?: number;
  confidence_self?: number;
  confidence_consistency?: number;
  confidence_struct?: number;
  confidence_conflict?: number;
  combined_confidence?: number;
  confidence?: number;
  variants?: unknown[];
  ladder_info?: unknown;
  ladder?: Record<string, string>;
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
  fidelity_pass?: boolean;
  fidelity_failures?: string[];
  voice_match?: boolean;
  output_target?: 'main' | 'placeholder' | 'discarded' | 'negotiation' | string;
  task_mode?: string;
  scope_match?: string;
  scope_reason?: string;
  template_anchor?: string;
  assumption?: string;
  behavior_mode?: string;
  consequence?: string;
  exception_conditions?: string;
  review_action?: string;
  transformation_note?: string;
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
  /** 行业词表（后端 yaml 里的 vocabulary 字段，返回的是数组）。 */
  vocabulary?: string[] | string;
  /** 关注要点（后端 yaml 里的 focus_points 字段，多行字符串）。 */
  focus_points?: string;
  /** 业务优先级覆盖（高/中/低）。 */
  priority_overrides?: Record<string, string>;
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
  output_target?: string;
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

/** v1.3: 任务级 extraction 覆盖（白名单，见后端 _apply_task_overrides） */
export interface ExtractionOverrides {
  granularity_level?: number;
  regulation_depth?: 'full' | 'limited';
  consistency_sampling?: boolean;
  industry_vocabulary?: string;
  industry_focus_points?: string;
}

export interface CreateBatchMeta {
  source_tag: string;
  contract_types: string[];
  our_party?: string;
  is_scanned?: boolean;
  is_redline?: boolean;
  is_case?: boolean;
  jurisdiction?: string;
  task_mode?: 'full_library' | 'template_focused' | 'template_strategy';
  scope_description?: string;
  /** v1.2: 任务级颗粒度档位（1–5），覆盖全局默认 */
  granularity_level?: number;
  /** v1.3: 任务级 extraction 覆盖（仅 meta[0] 生效） */
  extraction_overrides?: ExtractionOverrides;
}

// ── Task presets（任务配置预设） ────────────────────────────────────

export interface TaskPresetSettings extends ExtractionOverrides {
  task_mode?: 'full_library' | 'template_focused' | 'template_strategy';
  scope_description?: string;
  our_party?: string;
  jurisdiction?: string;
  industry_preset?: string | null;
}

export interface TaskPreset {
  name: string;
  settings: TaskPresetSettings;
  updated_at?: string;
}

export function fetchTaskPresets(): Promise<TaskPreset[]> {
  return request<TaskPreset[]>('/api/task-presets');
}

export function saveTaskPreset(name: string, settings: TaskPresetSettings): Promise<TaskPreset> {
  return request<TaskPreset>(`/api/task-presets/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings }),
  });
}

export function deleteTaskPreset(name: string): Promise<void> {
  return request<void>(`/api/task-presets/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export interface PreviewClassifyResponse {
  filename: string;
  suggested_source_tag: string;
  suggested_contract_types: string[];
  suggested_our_party: string;
  confidence: number;
  source_confidence?: number;
  contract_confidence?: number;
  party_confidence?: number;
  auto_apply?: boolean;
  auto_apply_source?: boolean;
  auto_apply_contract?: boolean;
  auto_apply_party?: boolean;
  suggested_is_case?: boolean;
  suggested_is_redline?: boolean;
  document_profile?: DocumentProfile;
  classification?: DocumentClassification;
  evidence: string[];
}

export interface DocumentClassification {
  document_genre: string;
  authority_level: string;
  confidence: number;
  feature_tags: {
    is_redline: boolean;
    is_case: boolean;
    is_template: boolean;
    has_rules: boolean;
  };
  industry_hints: string[];
  reasoning: string;
  evidence: string[];
  source_tag: string;
  source_priority: number;
  is_redline: boolean;
  is_case: boolean;
  /** v1.2: LLM 与关键词预筛分歧且置信不足 → 需用户确认 */
  needs_confirmation?: boolean;
  alternative_genre?: string;
}

export interface DocumentProfile {
  document_genre?: string;
  document_type?: string;
  genre?: string;
  authority_level?: string;
  primary_theme?: string;
  primary_legal_topic?: string;
  main_topic?: string;
  secondary_scenarios?: string[] | string;
  auxiliary_scenarios?: string[] | string;
  processing_suggestion?: string;
  processing_advice?: string;
  confidence?: number | string;
  classification_mode?: string;
  evidence?: string[];
}

export function previewClassify(file: File): Promise<PreviewClassifyResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return request<PreviewClassifyResponse>('/api/preview-classify', {
    method: 'POST',
    body: formData,
  });
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

/**
 * Subscribe to real-time batch progress via SSE.
 * Falls back to polling if SSE connection fails.
 * Returns a cleanup function.
 */
export function subscribeBatchProgress(
  id: string,
  onProgress: (progress: BatchProgress) => void,
  onDone?: () => void,
): () => void {
  const url = `/api/batches/${encodeURIComponent(id)}/progress/stream`;
  let closed = false;
  let pollTimer: number | null = null;

  const stopPolling = () => {
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  };

  const isDone = (status: string) => status === 'success' || status === 'partial' || status === 'failed';

  const es = new EventSource(url);

  es.onmessage = (event) => {
    if (closed) return;
    try {
      const data = JSON.parse(event.data) as BatchProgress;
      onProgress(data);
      if (isDone(data.status)) {
        closed = true;
        es.close();
        onDone?.();
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    if (closed) return;
    if (pollTimer !== null) return;
    // SSE failed; fall back to polling.
    es.close();
    pollTimer = window.setInterval(async () => {
      if (closed) {
        stopPolling();
        return;
      }
      try {
        const data = await fetchBatchProgress(id);
        if (closed) return;
        onProgress(data);
        if (isDone(data.status)) {
          closed = true;
          stopPolling();
          onDone?.();
        }
      } catch {
        // keep polling
      }
    }, 1500);
  };

  return () => {
    closed = true;
    es.close();
    stopPolling();
  };
}

export function fetchBatchRules(id: string, filters: BatchRuleFilters = {}): Promise<RuleListResponse> {
  const qs = buildQueryString(filters as Record<string, unknown>);
  return request<RuleListResponse>(`/api/batches/${encodeURIComponent(id)}/rules${qs}`);
}

export type ExportKind =
  | 'main-csv'
  | 'metadata-csv'
  | 'conflict-report'
  | 'change-set'
  | 'placeholders-csv'
  | 'discarded-csv'
  | 'negotiation-csv'
  | 'out-of-scope-csv'
  | 'template-strategy'
  | 'summary';

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

export interface CancelBatchResponse {
  batch_id: string;
  status: string;
  cancel_requested: boolean;
}

export function cancelBatch(id: string): Promise<CancelBatchResponse> {
  return request<CancelBatchResponse>(`/api/batches/${encodeURIComponent(id)}/cancel`, {
    method: 'POST',
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


// ── Archive API ─────────────────────────────────────────────────────

export interface ArchiveFileClassification {
  original_name: string;
  file_size: number;
  document_type: string;
  authority_level: string;
  primary_topic: string;
  source_tag: string;
  confidence: number;
  evidence: string[];
  category_dir: string;
  target_filename: string;
  llm_enhanced: boolean;
  llm_category: string | null;
  llm_summary: string | null;
  llm_confidence: number | null;
}

export interface ArchiveClassifyResponse {
  session_id: string;
  total_files: number;
  files: ArchiveFileClassification[];
  categories: Record<string, number>;
}

export interface ArchiveResult {
  archive_id: string;
  timestamp: string;
  total_files: number;
  high_confidence: number;
  low_confidence: number;
  directory_tree: Record<string, string[]>;
  files: ArchiveFileClassification[];
}

export function archiveClassify(files: File[], useLlm: boolean = false): Promise<ArchiveClassifyResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('use_llm', useLlm ? 'true' : 'false');
  return request<ArchiveClassifyResponse>('/api/archive/classify', {
    method: 'POST',
    body: formData,
  });
}

export function archiveUpdateClassification(
  sessionId: string,
  updates: Array<{ original_name: string; category_dir: string }>,
): Promise<{ session_id: string; files: ArchiveFileClassification[] }> {
  return request('/api/archive/classify/' + encodeURIComponent(sessionId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export function archiveConfirm(sessionId: string): Promise<ArchiveResult> {
  return request<ArchiveResult>('/api/archive/confirm/' + encodeURIComponent(sessionId), {
    method: 'POST',
  });
}

export function fetchArchiveResults(): Promise<ArchiveResult[]> {
  return request<ArchiveResult[]>('/api/archive/results');
}

export function fetchArchiveCategories(): Promise<Record<string, string[]>> {
  return request<Record<string, string[]>>('/api/archive/categories');
}


// ── Skill Generation API ────────────────────────────────────────────

export interface SkillGenerateRequest {
  domain_name: string;
  party_perspectives: string[];
  include_drafting: boolean;
  llm_enhance: boolean;
}

export interface SkillGenerateResponse {
  skill_id: string;
  status: string;
  file_count: number;
  download_url: string;
}

export function generateSkill(batchId: string, config: SkillGenerateRequest): Promise<SkillGenerateResponse> {
  return request<SkillGenerateResponse>(`/api/batches/${encodeURIComponent(batchId)}/generate-skill`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function downloadSkillZip(batchId: string): void {
  window.open(`/api/batches/${encodeURIComponent(batchId)}/exports/skill-zip`, '_blank');
}
