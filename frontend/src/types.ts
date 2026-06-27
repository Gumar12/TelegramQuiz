export interface Question {
  id: string;
  source_item_id?: number;
  date?: string;
  section?: string;
  context_title?: string;
  context?: string;
  media?: string[];
  question: string;
  options: string[];
  correct: number; // Index of correct option (0-indexed)
  backend_correct?: number | number[];
  explanation?: string;
  explanation_full?: string;
  type?: string;
  source?: string;
  quality_flags?: string[];
  needs_distractor_review?: boolean;
  warnings?: string[];
}

export interface QuizGroup {
  id: string;
  name: string; // e.g. "19 мая УТРО"
  allow_duplicate_questions?: boolean;
  date: string;
  description: string;
  questions: Question[];
  status: 'draft' | 'review' | 'ready';
}

export interface TaskLog {
  time: string;
  message: string;
  type: 'info' | 'success' | 'warn' | 'error' | 'terminal';
}

export type TaskStatus = 'idle' | 'parsing' | 'normalizing' | 'validating' | 'uploading';

export interface PipelineState {
  status: TaskStatus;
  progress: number; // 0 to 100
  currentGroup: string;
  currentStep: string;
  eta: number; // Seconds remaining
  logs: TaskLog[];
  warningsFound: string[];
  activeJobId?: string;
  error?: string;
  result?: Record<string, any> | null;
}

export interface GroupSummary {
  id: string;
  name: string;
  description: string;
  questions_count: number;
  path: string;
}

export interface ValidationReport {
  questions_total: number;
  multi_answer_count: number;
  context_count: number;
  media_count: number;
  correct_position_counts: Record<string, number>;
  errors?: Array<Record<string, any>>;
  warnings: Array<Record<string, any>>;
}

export interface JobSnapshot {
  id: string;
  type: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  stage: string;
  current_group: string;
  current_step: string;
  eta: number;
  logs: TaskLog[];
  warnings: string[];
  result?: Record<string, any> | null;
  error?: string;
  cancel_requested: boolean;
}

export interface WaitForJobOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  pollMs?: number;
}

export interface JobEvent {
  index: number;
  job_id: string;
  status: JobSnapshot['status'];
  type: string;
  stage: string;
  progress: number;
  current_group: string;
  current_step: string;
  eta: number;
  message: string;
  log: TaskLog;
  warnings: string[];
  result?: Record<string, any> | null;
  error?: string;
}

export interface HealthResponse {
  ok: boolean;
  time?: number;
}

export interface AccountProfilePublic {
  id: string;
  display_name: string;
  status: string;
  session_path_basename: string;
  telegram_phone_masked: string;
  is_active: boolean;
}

export type TelegramLoginStep =
  | 'code_sent'
  | 'password_required'
  | 'authorized'
  | 'failed'
  | 'expired'
  | 'cancelled';

export interface TelegramLoginCodeSentResponse {
  login_id: string;
  profile_id: string;
  step: 'code_sent';
  phone_masked: string;
  expires_at: string;
}

export interface TelegramLoginPasswordRequiredResponse {
  login_id: string;
  step: 'password_required';
}

export interface TelegramLoginQrPendingResponse {
  login_id: string;
  profile_id: string;
  step: 'qr_pending';
  qr_url: string;
  qr_image: string;
  expires_at: string;
}

export interface TelegramLoginErrorResponse {
  login_id: string;
  profile_id: string;
  step: 'error';
  error: string;
}

export interface TelegramLoginAuthorizedResponse {
  step: 'authorized';
  account: AccountProfilePublic;
}

export type TelegramLoginStartResponse =
  | TelegramLoginCodeSentResponse
  | TelegramLoginAuthorizedResponse;

export type TelegramLoginQrStartResponse =
  | TelegramLoginQrPendingResponse
  | TelegramLoginAuthorizedResponse;

export type TelegramLoginStatusResponse =
  | TelegramLoginCodeSentResponse
  | TelegramLoginPasswordRequiredResponse
  | TelegramLoginQrPendingResponse
  | TelegramLoginErrorResponse
  | TelegramLoginAuthorizedResponse;

export type TelegramLoginCodeResponse =
  | TelegramLoginPasswordRequiredResponse
  | TelegramLoginAuthorizedResponse;

export type UploadRunStatus =
  | 'queued'
  | 'review_required'
  | 'running'
  | 'paused'
  | 'rollback'
  | 'skipped_forward'
  | 'failed'
  | 'cancelled'
  | 'cancelled_replaced'
  | 'completed';

export type SpeedProbeRunStatus =
  | 'running'
  | 'cooldown'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled_replaced';

export type SafeRunError = Record<string, unknown> | null;

export interface UploadRunStatusSnapshot {
  kind: 'upload';
  run_id: string;
  status: UploadRunStatus;
  quiz_name: string;
  quiz_file_basename: string;
  account_profile_id: string;
  speed: string;
  start_question_index: number;
  next_question_index: number;
  source_question_count: number;
  uploaded_count: number;
  skipped_count: number;
  cooldown_count: number;
  estimated_remaining_seconds: number;
  has_protected_progress: boolean;
  last_error: SafeRunError;
  share_link: string | null;
  auto_resume_enabled: boolean;
  auto_resume_delay_seconds: number;
  auto_resume_next_at: string | null;
  auto_resume_attempts: number;
  auto_resume_last_job_id: string | null;
  auto_resume_last_scheduled_at: string | null;
  updated_at: string;
}

export interface SpeedProbeRunStatusSnapshot {
  kind: 'speed_probe';
  probe_id: string;
  status: SpeedProbeRunStatus;
  quiz_name: string;
  source_quiz_file_basename: string;
  account_profile_id: string;
  first_limit_at_question: number | null;
  limit_event_count: number;
  cleanup_status: string;
  has_protected_progress: boolean;
  last_error: SafeRunError;
  updated_at: string;
}

export type RunStatusSnapshot = UploadRunStatusSnapshot | SpeedProbeRunStatusSnapshot;

export type ActiveRunResponse =
  | { active: false }
  | (RunStatusSnapshot & { active: true });

export interface SettingsResponse {
  workspace_dir: string;
  source_path: string;
  media_dir: string;
  quizzes_dir: string;
  eta?: {
    bot_response_seconds: number;
    speed_profiles?: Record<string, Record<string, number>>;
  };
  paths: {
    workspace: string;
    source: string;
    media: string;
    quizzes: string;
  };
}

export interface DeepSeekKeyStatus {
  configured: boolean;
  masked: string;
  source: 'runtime' | 'env' | null;
}
