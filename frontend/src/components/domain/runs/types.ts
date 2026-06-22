export type RunStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'cooldown'
  | 'blocked'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type RunQueueStatus = 'ready' | 'needs_review' | 'blocked' | 'running';

export type RunSummary = {
  accountName: string;
  autoResumeAttempts?: number;
  autoResumeDelaySeconds?: number;
  autoResumeEnabled?: boolean;
  autoResumeLastScheduledAt?: string;
  autoResumeNextAt?: string;
  completedQuestions?: number;
  continueFrom?: number;
  currentQuestion?: number;
  disabledReason?: string;
  estimatedRemainingSeconds?: number;
  id: string;
  lastError?: string;
  nextQuestionIndex?: number;
  participantsActive?: number;
  participantsCompleted?: number;
  participantsTotal?: number;
  progress: number;
  quizTitle: string;
  rollbackTo?: number;
  startedAt?: string;
  startQuestionIndex?: number;
  status: RunStatus;
  totalQuestions: number;
  updatedAt?: string;
};

export type RunQueueItem = {
  disabledReason?: string;
  id: string;
  questionCount?: number;
  status: RunQueueStatus;
  title: string;
};

export type RunQueueMoveDirection = 'up' | 'down';
