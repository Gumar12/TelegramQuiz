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

export interface SourceGroupSummary {
  id: string;
  name: string;
  questions_count: number;
  generated: boolean;
  path: string;
}

export interface ValidationReport {
  questions_total: number;
  multi_answer_count: number;
  context_count: number;
  media_count: number;
  correct_position_counts: Record<string, number>;
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
