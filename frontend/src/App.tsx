import { useEffect, useMemo, useRef, useState } from 'react';
import { api, mediaUrl } from './api';
import type { AppRouteId } from './app/routes';
import { AppShell } from './components/layout/AppShell';
import { ArchiveDeleteQuizModal, StopRunModal, SwitchAccountModal, TelegramErrorModal, UnsavedChangesModal } from './components/modals';
import type { PublicAccountProfile } from './components/domain/accounts';
import type { RunSummary } from './components/domain/runs';
import DashboardScreen, {
  type DashboardQuizAction,
  type DashboardQuizRow,
  type DashboardRunSummary,
} from './screens/DashboardScreen';
import CreateQuizScreen from './screens/CreateQuizScreen';
import QuizEditorScreen, { type QuizEditorExitRequest, type QuizEditorGroup } from './screens/QuizEditorScreen';
import QuizzesScreen, { type QuizListItem } from './screens/QuizzesScreen';
import RunsScreen, { type LaunchQuizCandidate } from './screens/RunsScreen';
import AccountsScreen, { type TelegramLoginPanelState } from './screens/AccountsScreen';
import SettingsScreen, { type SettingsValues } from './screens/SettingsScreen';
import {
  closeModal,
  openModal,
  useModalStore,
  type AccountConnectionStatus,
  type AccountOption,
} from './state/modalStore';
import type {
  AccountProfilePublic,
  ActiveRunResponse,
  JobEvent,
  JobSnapshot,
  PipelineState,
  QuizGroup,
  RunStatusSnapshot,
  SettingsResponse,
  TaskStatus,
  ValidationReport,
} from './types';

const idlePipeline: PipelineState = {
  status: 'idle',
  progress: 0,
  currentGroup: '',
  currentStep: '',
  eta: 0,
  logs: [],
  warningsFound: [],
  result: null,
};

const defaultWorkspaceConfig = {
  workspaceDir: '.',
  sourcePath: 'questions_v2.json',
  outputDir: 'quizzes',
  mediaRoot: '.',
};

const SETTINGS_STORAGE_KEY = 'quizbot.platform.settings';

type TelegramLoginUiState = TelegramLoginPanelState & {
  loginId?: string;
  profileId: string;
};

function taskStatusForJob(type: string, fallback: TaskStatus): TaskStatus {
  if (type.includes('create')) return 'parsing';
  if (type.includes('parse')) return 'parsing';
  if (type.includes('generate')) return 'normalizing';
  if (type.includes('validate')) return 'validating';
  if (type.includes('upload')) return 'uploading';
  return fallback;
}

function countQuizIssues(group: QuizGroup): number {
  return group.questions.reduce(
    (total, question) => total + (question.warnings?.length ?? 0) + (question.quality_flags?.length ?? 0),
    0,
  );
}

function rowFromQuizGroup(group: QuizGroup): DashboardQuizRow {
  const issues = countQuizIssues(group);

  if (group.status === 'ready') {
    return {
      action: 'launch',
      actionLabel: 'Запустить',
      errors: issues,
      id: group.id,
      name: group.name,
      stage: 'Готов к запуску',
      status: issues > 0 ? 'Есть предупреждения' : 'Готов',
      tone: issues > 0 ? 'warning' : 'success',
    };
  }

  if (group.status === 'review') {
    return {
      action: 'fix',
      actionLabel: 'Исправить',
      errors: Math.max(issues, 1),
      id: group.id,
      name: group.name,
      stage: 'Проверка JSON',
      status: 'Нужно исправить',
      tone: 'danger',
    };
  }

  return {
    action: 'edit',
    actionLabel: 'Открыть',
    errors: issues,
    id: group.id,
    name: group.name,
    stage: 'Черновик',
    status: 'В работе',
    tone: 'neutral',
  };
}

function mapAccountStatus(status: string): AccountConnectionStatus {
  const normalized = status.toLowerCase();

  if (['connected', 'authorized', 'active', 'enabled_authorized', 'ready', 'ok'].includes(normalized)) {
    return 'connected';
  }

  if (normalized === 'enabled') {
    return 'disconnected';
  }

  if (['needs_reconnect', 'needs-auth', 'needs_auth', 'expired', 'missing_session'].includes(normalized)) {
    return 'needs_reconnect';
  }

  if (['disabled', 'off'].includes(normalized)) {
    return 'disabled';
  }

  return 'disconnected';
}

function accountName(account: AccountProfilePublic | null | undefined): string {
  return account?.display_name?.trim() || account?.id || 'Нет аккаунта';
}

function errorLabel(error: unknown): string {
  if (!(error instanceof Error)) return 'Не удалось выполнить действие';
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown };
    if (typeof parsed.detail === 'string') {
      if (parsed.detail === 'Telegram login code expired') {
        return 'Код Telegram истёк. Запросите новый код.';
      }
      if (parsed.detail === 'Telegram code request expired') {
        return 'Запрос кода Telegram устарел. Запросите новый код.';
      }
      if (parsed.detail === 'Telegram rejected the login code') {
        return 'Telegram отклонил код. Проверьте код или запросите новый.';
      }
      if (parsed.detail === 'Telegram login flow expired') {
        return 'Вход в Telegram истёк. Запросите новый код.';
      }
      return parsed.detail;
    }
  } catch {
    // Keep the original message when it is not a JSON error response.
  }
  return error.message || 'Не удалось выполнить действие';
}

function toAccountOption(account: AccountProfilePublic): AccountOption {
  const status = mapAccountStatus(account.status);

  return {
    active: account.is_active,
    disabledReason: status === 'disabled' ? 'Профиль отключён' : undefined,
    id: account.id,
    maskedPhone: account.telegram_phone_masked || undefined,
    name: accountName(account),
    status,
  };
}

function toPublicAccountProfile(account: AccountProfilePublic): PublicAccountProfile {
  const status = mapAccountStatus(account.status);

  return {
    active: account.is_active,
    disabledReason: status === 'disabled' ? 'Профиль отключён' : undefined,
    enabled: status !== 'disabled',
    id: account.id,
    maskedPhone: account.telegram_phone_masked || undefined,
    name: accountName(account),
    sessionState: status === 'connected' ? 'authorized' : status === 'disabled' ? 'missing' : 'needs_auth',
    status,
  };
}

function getRunId(run: RunStatusSnapshot): string {
  return run.kind === 'upload' ? run.run_id : run.probe_id;
}

function mapRunStatus(status: string): RunSummary['status'] {
  if (status === 'running') return 'running';
  if (status === 'cooldown') return 'cooldown';
  if (status === 'paused' || status === 'rollback' || status === 'skipped_forward') return 'paused';
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  if (status === 'cancelled' || status === 'cancelled_replaced') return 'cancelled';
  if (status === 'queued') return 'queued';
  return 'blocked';
}

function formatSafeError(error: Record<string, unknown> | null | undefined): string | undefined {
  if (!error) return undefined;
  const message = error.message ?? error.detail ?? error.error;
  if (typeof message === 'string' && message.trim()) return message;
  return 'Backend сообщил об ошибке запуска.';
}

function toRunSummary(run: RunStatusSnapshot, accountNames: Map<string, string>): RunSummary {
  const id = getRunId(run);
  const accountNameValue = accountNames.get(run.account_profile_id) ?? run.account_profile_id;

  if (run.kind === 'upload') {
    const totalQuestions = Math.max(0, run.source_question_count);
    const completedQuestions = Math.max(0, run.uploaded_count + run.skipped_count);
    const progress = totalQuestions > 0 ? Math.round((completedQuestions / totalQuestions) * 100) : run.status === 'completed' ? 100 : 0;
    const currentQuestion =
      run.next_question_index <= totalQuestions
        ? run.next_question_index
        : totalQuestions > 0
          ? totalQuestions
          : undefined;

    return {
      accountName: accountNameValue,
      autoResumeAttempts: run.auto_resume_attempts,
      autoResumeDelaySeconds: run.auto_resume_delay_seconds,
      autoResumeEnabled: run.auto_resume_enabled,
      autoResumeLastScheduledAt: run.auto_resume_last_scheduled_at || undefined,
      autoResumeNextAt: run.auto_resume_next_at || undefined,
      completedQuestions,
      currentQuestion,
      estimatedRemainingSeconds: Math.max(0, Number(run.estimated_remaining_seconds) || 0),
      id,
      lastError: formatSafeError(run.last_error),
      nextQuestionIndex: run.next_question_index,
      progress,
      quizTitle: run.quiz_name || run.quiz_file_basename,
      rollbackTo: Math.max(1, run.next_question_index - 1),
      startQuestionIndex: run.start_question_index,
      status: mapRunStatus(run.status),
      totalQuestions,
      updatedAt: run.updated_at,
    };
  }

  return {
    accountName: accountNameValue,
    completedQuestions: run.status === 'completed' ? 1 : 0,
    id,
    lastError: formatSafeError(run.last_error),
    progress: run.status === 'completed' ? 100 : run.status === 'running' || run.status === 'cooldown' ? 50 : 0,
    quizTitle: run.quiz_name || run.source_quiz_file_basename,
    status: mapRunStatus(run.status),
    totalQuestions: 1,
    updatedAt: run.updated_at,
  };
}

function uploadProgressFromPipeline(pipeline: PipelineState): { done: number; total: number; stage?: string } | null {
  const value = pipeline.result?.upload_progress;
  if (!value || typeof value !== 'object') return null;
  const done = Number((value as Record<string, unknown>).done);
  const total = Number((value as Record<string, unknown>).total);
  const stage = (value as Record<string, unknown>).stage;
  if (!Number.isFinite(done) || !Number.isFinite(total) || total < 0) return null;
  return {
    done: Math.max(0, done),
    stage: typeof stage === 'string' ? stage : undefined,
    total: Math.max(0, total),
  };
}

function toDashboardRun(run: RunSummary | null): DashboardRunSummary | undefined {
  if (!run) return undefined;
  const dashboardStatus: DashboardRunSummary['status'] =
    run.status === 'blocked' || run.status === 'cancelled'
      ? 'failed'
      : run.status === 'cooldown'
        ? 'running'
        : run.status;

  return {
    currentGroup: run.quizTitle,
    currentStep: run.lastError ?? `Аккаунт: ${run.accountName}`,
    progress: run.progress,
    status: dashboardStatus,
    title: run.quizTitle,
  };
}

function pipelineToRunSummary(
  pipeline: PipelineState,
  group: QuizGroup | null,
  accountNameValue: string,
): RunSummary | null {
  if (!pipeline.activeJobId) return null;

  const runResult = pipeline.result?.run;
  if (runResult && typeof runResult === 'object' && (runResult as Record<string, unknown>).kind === 'upload') {
    const run = runResult as Record<string, unknown>;
    const totalQuestions = Math.max(0, Number(run.source_question_count) || 0);
    const completedQuestions = Math.max(0, (Number(run.uploaded_count) || 0) + (Number(run.skipped_count) || 0));
    const nextQuestionIndex = Number(run.next_question_index) || undefined;
    const progress = totalQuestions > 0
      ? Math.round((Math.min(completedQuestions, totalQuestions) / totalQuestions) * 100)
      : run.status === 'completed'
        ? 100
        : 0;
    return {
      accountName: accountNameValue,
      completedQuestions,
      currentQuestion: nextQuestionIndex && totalQuestions > 0 ? Math.min(nextQuestionIndex, totalQuestions) : undefined,
      estimatedRemainingSeconds: Math.max(0, Number(run.estimated_remaining_seconds) || 0),
      id: String(run.run_id),
      lastError: formatSafeError(run.last_error as Record<string, unknown> | null | undefined),
      nextQuestionIndex,
      progress,
      quizTitle: String(run.quiz_name || pipeline.currentGroup || group?.name || 'Новый запуск'),
      rollbackTo: nextQuestionIndex ? Math.max(1, nextQuestionIndex - 1) : undefined,
      startQuestionIndex: Number(run.start_question_index) || undefined,
      status: mapRunStatus(String(run.status || 'running')),
      totalQuestions,
      updatedAt: typeof run.updated_at === 'string' ? run.updated_at : pipeline.currentStep || undefined,
    };
  }

  const uploadProgress = uploadProgressFromPipeline(pipeline);
  const totalQuestions = uploadProgress?.total || group?.questions.length || 0;
  const completedQuestions = Math.min(totalQuestions, uploadProgress?.done ?? 0);
  const progress = uploadProgress && totalQuestions > 0
    ? Math.round((completedQuestions / totalQuestions) * 100)
    : totalQuestions > 0
      ? Math.round((completedQuestions / totalQuestions) * 100)
    : Math.max(0, Math.min(100, Math.round(pipeline.progress)));
  const currentQuestion = totalQuestions > 0
    ? Math.max(1, Math.min(totalQuestions, completedQuestions + 1))
    : undefined;
  const status: RunSummary['status'] = pipeline.error
    ? 'failed'
    : pipeline.status === 'uploading'
      ? 'running'
      : progress >= 100
        ? 'completed'
        : 'queued';

  return {
    accountName: accountNameValue,
    completedQuestions,
    currentQuestion,
    estimatedRemainingSeconds: pipeline.eta > 0 ? pipeline.eta : undefined,
    id: pipeline.activeJobId,
    lastError: pipeline.error,
    progress,
    quizTitle: pipeline.currentGroup || group?.name || 'Новый запуск',
    status,
    totalQuestions,
    updatedAt: pipeline.currentStep || undefined,
  };
}

function editorGroupToQuizGroup(group: QuizEditorGroup): QuizGroup {
  return {
    ...group,
    date: group.date ?? '',
    description: group.description ?? '',
    questions: group.questions.map((question) => ({
      ...question,
      // Preserve a missing/null correct answer as an invalid sentinel (-1)
      // instead of silently defaulting to the first option; validation must
      // keep blocking it before launch.
      correct: typeof question.correct === 'number' ? question.correct : -1,
      options: Array.isArray(question.options) ? question.options : [],
      question: question.question ?? '',
    })),
    status: group.status === 'ready' || group.status === 'review' ? group.status : 'draft',
  };
}

function settingsFromResponse(response: SettingsResponse | null, workspaceConfig: typeof defaultWorkspaceConfig): Partial<SettingsValues> {
  return {
    defaultLaunch: {
      contextMode: 'per-question',
      quizBotResponseSec: Math.max(0, Number(response?.eta?.bot_response_seconds) || 2),
      segmentSize: 50,
      shuffleOptions: false,
      speed: 'normal',
    },
    workspaceLabel: response?.workspace_dir || workspaceConfig.workspaceDir,
  };
}

function readStoredSettings(): Partial<SettingsValues> | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed as Partial<SettingsValues> : null;
  } catch {
    return null;
  }
}

function writeStoredSettings(settings: SettingsValues | null) {
  if (typeof window === 'undefined') return;
  if (settings) {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    return;
  }
  window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
}

export default function App() {
  const [activeRoute, setActiveRoute] = useState<AppRouteId>('dashboard');
  const [quizGroups, setQuizGroups] = useState<QuizGroup[]>([]);
  const [workspaceConfig, setWorkspaceConfig] = useState(defaultWorkspaceConfig);
  const [pipeline, setPipeline] = useState<PipelineState>(idlePipeline);
  const [accounts, setAccounts] = useState<AccountProfilePublic[]>([]);
  const [currentAccount, setCurrentAccount] = useState<AccountProfilePublic | null>(null);
  const [runs, setRuns] = useState<RunStatusSnapshot[]>([]);
  const [activeRun, setActiveRun] = useState<ActiveRunResponse>({ active: false });
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [storedSettings, setStoredSettings] = useState<Partial<SettingsValues> | null>(() => readStoredSettings());
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [telegramLogin, setTelegramLogin] = useState<TelegramLoginUiState | null>(null);
  const [pendingEditorExit, setPendingEditorExit] = useState<QuizEditorExitRequest | null>(null);
  const [archiveDeleteError, setArchiveDeleteError] = useState('');
  const [archiveDeleteSubmitting, setArchiveDeleteSubmitting] = useState(false);
  const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);
  const [stopError, setStopError] = useState('');
  const [stoppingRunIds, setStoppingRunIds] = useState<Set<string>>(new Set());
  const modal = useModalStore();
  const activeEventSource = useRef<EventSource | null>(null);
  const activeJobStatus = useRef<TaskStatus>('idle');
  const jobWatchGeneration = useRef(0);
  const telegramLoginRequest = useRef(0);
  const jobWaitAbort = useRef<AbortController>(new AbortController());
  const refreshRunsInFlight = useRef(false);

  const refreshGroups = async () => {
    try {
      setQuizGroups(await api.getGroups());
    } catch (error) {
      console.error(error);
      setQuizGroups([]);
    }
  };

  const refreshAccounts = async () => {
    const [accountsResult, currentResult] = await Promise.allSettled([
      api.getAccounts(),
      api.getCurrentAccount(),
    ]);

    const nextAccounts = accountsResult.status === 'fulfilled' ? accountsResult.value : [];
    if (accountsResult.status === 'rejected') console.error(accountsResult.reason);
    if (currentResult.status === 'rejected') console.error(currentResult.reason);

    setAccounts(nextAccounts);
    setCurrentAccount(
      currentResult.status === 'fulfilled'
        ? currentResult.value
        : nextAccounts.find((account) => account.is_active) ?? null,
    );
  };

  const refreshRuns = async () => {
    if (refreshRunsInFlight.current) return;
    refreshRunsInFlight.current = true;
    try {
      const [runsResult, activeRunResult] = await Promise.allSettled([
        api.getRuns(),
        api.getActiveRun(),
      ]);

      if (runsResult.status === 'fulfilled') setRuns(runsResult.value);
      else {
        console.error(runsResult.reason);
        setRuns([]);
      }

      if (activeRunResult.status === 'fulfilled') setActiveRun(activeRunResult.value);
      else {
        console.error(activeRunResult.reason);
        setActiveRun({ active: false });
      }
    } finally {
      refreshRunsInFlight.current = false;
    }
  };

  const refreshSettings = async () => {
    try {
      const nextSettings = await api.getSettings();
      setSettings(nextSettings);
      setWorkspaceConfig((current) => ({
        // workspace_dir из settings — абсолютный корень сервера (информационное поле).
        // Поле «Рабочая папка» при создании квиза требует относительный путь внутри data,
        // поэтому держим относительный дефолт и не затираем его абсолютным значением.
        workspaceDir: current.workspaceDir,
        sourcePath: nextSettings.source_path || current.sourcePath,
        outputDir: nextSettings.quizzes_dir || current.outputDir,
        mediaRoot: nextSettings.media_dir || current.mediaRoot,
      }));
    } catch (error) {
      console.error(error);
      setSettings(null);
    }
  };

  useEffect(() => {
    // Свежий контроллер на каждый mount: цикл StrictMode mount→cleanup→mount
    // не оставит нас с навсегда-аборченным сигналом для waitForJob.
    const abortController = new AbortController();
    jobWaitAbort.current = abortController;
    refreshGroups();
    refreshAccounts();
    refreshRuns();
    refreshSettings();
    return () => {
      jobWatchGeneration.current += 1;
      activeEventSource.current?.close();
      // Abort any in-flight waitForJob polling so it stops promptly on unmount.
      abortController.abort();
    };
  }, []);

  // Fallback run-polling: when no live EventSource is streaming job updates but
  // there are still non-terminal runs, periodically refresh so the runs view
  // converges without depending on the original SSE connection.
  const hasNonTerminalRun = useMemo(() => {
    const isNonTerminal = (status: string) =>
      !['completed', 'failed', 'cancelled', 'cancelled_replaced'].includes(status);
    if (activeRun.active && isNonTerminal(activeRun.status)) return true;
    return runs.some((run) => isNonTerminal(run.status));
  }, [activeRun, runs]);

  useEffect(() => {
    if (!hasNonTerminalRun) return;
    const interval = window.setInterval(() => {
      if (activeEventSource.current) return;
      void refreshRuns();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [hasNonTerminalRun]);

  // Снимаем переходную пометку «останавливается», когда refreshRuns показал
  // терминальный статус — индикация исчезает только после реальной остановки.
  useEffect(() => {
    setStoppingRunIds((current) => {
      if (current.size === 0) return current;
      const terminal = new Set(['cancelled', 'cancelled_replaced', 'failed', 'completed']);
      const next = new Set(current);
      runs.forEach((run) => {
        if (terminal.has(run.status)) next.delete(getRunId(run));
      });
      return next.size === current.size ? current : next;
    });
  }, [runs]);

  const applyJobEvent = (event: JobEvent) => {
    const running = event.status === 'running';
    const nextStatus = running ? taskStatusForJob(event.type, activeJobStatus.current) : 'idle';
    setPipeline((prev) => ({
      ...prev,
      status: nextStatus,
      progress: event.progress,
      currentGroup: event.current_group,
      currentStep: event.current_step,
      eta: event.eta,
      logs: [...prev.logs, event.log],
      warningsFound: event.warnings,
      activeJobId: event.job_id,
      error: event.error,
      result: event.result || prev.result,
    }));

    if (!running) {
      activeEventSource.current?.close();
      activeEventSource.current = null;
      refreshGroups();
      refreshRuns();
    }
  };

  const applyJobSnapshot = (snapshot: JobSnapshot) => {
    const running = snapshot.status === 'running';
    const nextStatus = running ? taskStatusForJob(snapshot.type, activeJobStatus.current) : 'idle';
    setPipeline((prev) => ({
      ...prev,
      status: nextStatus,
      progress: snapshot.progress,
      currentGroup: snapshot.current_group,
      currentStep: snapshot.current_step,
      eta: snapshot.eta,
      logs: snapshot.logs.length > 0 ? snapshot.logs : prev.logs,
      warningsFound: snapshot.warnings,
      activeJobId: snapshot.id,
      error: snapshot.error,
      result: snapshot.result || prev.result,
    }));

    if (!running) {
      activeEventSource.current?.close();
      activeEventSource.current = null;
      refreshGroups();
      refreshRuns();
    }
  };

  const recoverJobWithPolling = async (jobId: string, generation: number) => {
    setPipeline((prev) => (
      prev.activeJobId === jobId && prev.status !== 'idle'
        ? { ...prev, currentStep: prev.currentStep || 'Ожидаем статус backend job...' }
        : prev
    ));

    try {
      const snapshot = await api.waitForJob(jobId, {
        signal: jobWaitAbort.current.signal,
        timeoutMs: 10 * 60 * 1000,
      });
      if (jobWatchGeneration.current !== generation) return;
      applyJobSnapshot(snapshot);
    } catch (error) {
      if (jobWatchGeneration.current !== generation) return;
      setPipeline((prev) => (
        prev.activeJobId === jobId
          ? {
              ...prev,
              status: 'idle',
              currentStep: 'Не удалось получить статус backend job.',
              error: errorLabel(error),
            }
          : prev
      ));
      refreshGroups();
      refreshRuns();
    }
  };

  const watchJob = (jobId: string, status: TaskStatus, groupName: string, routeOnStart?: AppRouteId | null) => {
    activeEventSource.current?.close();
    const generation = jobWatchGeneration.current + 1;
    jobWatchGeneration.current = generation;
    activeJobStatus.current = status;
    setPipeline({
      ...idlePipeline,
      status,
      currentGroup: groupName,
      currentStep: 'Подключение к backend job...',
      activeJobId: jobId,
    });
    if (routeOnStart !== null) {
      setActiveRoute(routeOnStart ?? (status === 'uploading' ? 'runs' : 'create'));
    }
    activeEventSource.current = api.subscribeJob(
      jobId,
      (event) => {
        if (jobWatchGeneration.current !== generation) return;
        applyJobEvent(event);
      },
      () => {
        if (jobWatchGeneration.current !== generation) return;
        activeEventSource.current?.close();
        activeEventSource.current = null;
        void recoverJobWithPolling(jobId, generation);
      },
    );
  };

  const createQuizFromDocx = async (file: File, title: string, description: string, workspaceDir: string, useAiParsing: boolean) => {
    const normalizedWorkspace = workspaceDir.trim() || '.';
    setWorkspaceConfig({
      workspaceDir: normalizedWorkspace,
      sourcePath: normalizedWorkspace === '.' ? 'questions_v2.json' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/questions_v2.json`,
      outputDir: normalizedWorkspace === '.' ? 'quizzes' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/quizzes`,
      mediaRoot: normalizedWorkspace,
    });
    const response = await api.createQuizFromDocx(file, title, description, normalizedWorkspace, useAiParsing);
    watchJob(response.job_id, 'parsing', title, 'create');
    const snapshot = await api.waitForJob(response.job_id, {
      signal: jobWaitAbort.current.signal,
    });
    await refreshGroups();
    if (snapshot.status === 'failed') {
      throw new Error(snapshot.error || 'Не удалось создать JSON из DOCX');
    }

    const createdGroups = Array.isArray(snapshot.result?.groups) ? snapshot.result.groups : [];
    const firstCreatedGroup = createdGroups.find((group): group is { id: string } => (
      typeof group === 'object'
      && group !== null
      && typeof (group as { id?: unknown }).id === 'string'
    ));
    if (firstCreatedGroup) {
      setSelectedGroupId(firstCreatedGroup.id);
    }
    setActiveRoute('editor');
  };

  const createQuizFromJson = async (file: File, title: string, description: string, workspaceDir: string) => {
    const normalizedWorkspace = workspaceDir.trim() || '.';
    setWorkspaceConfig({
      workspaceDir: normalizedWorkspace,
      sourcePath: normalizedWorkspace === '.' ? 'questions_v2.json' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/questions_v2.json`,
      outputDir: normalizedWorkspace === '.' ? 'quizzes' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/quizzes`,
      mediaRoot: normalizedWorkspace,
    });
    const saved = await api.importQuizJson(file, title.trim() || file.name.replace(/\.[^.]+$/, ''), description, normalizedWorkspace);
    setQuizGroups((current) => [saved, ...current.filter((group) => group.id !== saved.id)]);
    setSelectedGroupId(saved.id);
    setActiveRoute('editor');
  };

  const createManualQuiz = async (title: string, workspaceDir: string) => {
    const normalizedWorkspace = workspaceDir.trim() || '.';
    setWorkspaceConfig({
      workspaceDir: normalizedWorkspace,
      sourcePath: normalizedWorkspace === '.' ? 'questions_v2.json' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/questions_v2.json`,
      outputDir: normalizedWorkspace === '.' ? 'quizzes' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/quizzes`,
      mediaRoot: normalizedWorkspace,
    });
    const saved = await api.createManualQuiz(title.trim() || 'Новый квиз', normalizedWorkspace);
    setQuizGroups((current) => [saved, ...current.filter((group) => group.id !== saved.id)]);
    setSelectedGroupId(saved.id);
    setActiveRoute('editor');
  };

  const validateGroup = async (groupId: string, strict: boolean): Promise<ValidationReport> => {
    const response = await api.validateGroup(groupId, strict);
    const snapshot = await api.waitForJob(response.job_id, {
      signal: jobWaitAbort.current.signal,
    });
    refreshGroups();
    if (snapshot.status === 'failed') {
      throw new Error(snapshot.error || 'Validation failed');
    }
    return snapshot.result?.report as ValidationReport;
  };

  const uploadGroup = async (options: {
    groupId: string;
    name: string;
    speed: 'normal' | 'fast';
    contextMode: 'once' | 'per-question';
    shuffleOptions: boolean;
    startFrom?: number;
  }) => {
    const response = await api.uploadGroup({
      group_id: options.groupId,
      name: options.name,
      speed: options.speed,
      context_send_mode: options.contextMode,
      shuffle_options: options.shuffleOptions,
      start_from: options.startFrom ?? 1,
    });
    watchJob(response.job_id, 'uploading', options.name, 'runs');
  };

  const cancelPipeline = async () => {
    if (!pipeline.activeJobId) return;
    await api.cancelJob(pipeline.activeJobId);
  };

  const handleUpdateGroup = async (groupId: string, updatedGroup: QuizGroup) => {
    const saved = await api.saveGroup({ ...updatedGroup, id: groupId });
    setQuizGroups((groups) => groups.map((group) => (group.id === groupId ? saved : group)));
  };

  const handleSaveSettings = async (nextSettings: SettingsValues) => {
    setSettingsSaving(true);
    try {
      const etaResponse = await api.updateEtaSettings({
        bot_response_seconds: nextSettings.defaultLaunch.quizBotResponseSec,
      });
      setStoredSettings(nextSettings);
      writeStoredSettings(nextSettings);
      setSettings((current) => current ? { ...current, eta: { ...(current.eta || {}), ...etaResponse.eta } } : current);
    } finally {
      setSettingsSaving(false);
    }
  };

  const handleResetSettings = () => {
    setStoredSettings(null);
    writeStoredSettings(null);
  };

  const saveEditorGroup = async (groupId: string, updatedGroup: QuizEditorGroup) => {
    await handleUpdateGroup(groupId, editorGroupToQuizGroup(updatedGroup));
  };

  const validateEditorGroup = async (groupId: string, updatedGroup: QuizEditorGroup) => {
    await saveEditorGroup(groupId, updatedGroup);
    return validateGroup(groupId, true);
  };

  const markEditorGroupReady = async (groupId: string, updatedGroup: QuizEditorGroup) => {
    await saveEditorGroup(groupId, updatedGroup);
    setSelectedGroupId(groupId);
    setActiveRoute('runs');
  };

  const uploadMedia = async (file: File): Promise<string> => {
    const uploaded = await api.uploadMedia(file);
    return uploaded.path;
  };

  const effectiveAccount = currentAccount ?? accounts.find((account) => account.is_active) ?? null;
  const effectiveAccountStatus = mapAccountStatus(effectiveAccount?.status ?? '');
  const accountOptions = useMemo(() => accounts.map(toAccountOption), [accounts]);
  const publicAccounts = useMemo(() => accounts.map(toPublicAccountProfile), [accounts]);
  const effectiveSettings = useMemo(
    () => {
      const responseSettings = settingsFromResponse(settings, workspaceConfig);
      return {
        ...responseSettings,
        ...(storedSettings || {}),
        defaultLaunch: {
          ...responseSettings.defaultLaunch,
          ...(storedSettings?.defaultLaunch || {}),
        },
      };
    },
    [settings, storedSettings, workspaceConfig],
  );
  const accountNames = useMemo(
    () => new Map(accounts.map((account) => [account.id, accountName(account)])),
    [accounts],
  );

  const runSummaries = useMemo(
    () => runs.map((run) => toRunSummary(run, accountNames)),
    [accountNames, runs],
  );

  const activeRunSummary = useMemo(() => {
    if (activeRun.active) return toRunSummary(activeRun, accountNames);
    return runSummaries.find((run) => run.status === 'running' || run.status === 'cooldown' || run.status === 'paused') ?? null;
  }, [accountNames, activeRun, runSummaries]);

  const pausableRunIds = useMemo(() => {
    const ids = new Set<string>();
    runs.forEach((run) => {
      if (run.kind === 'upload') ids.add(run.run_id);
    });
    if (activeRun.active && activeRun.kind === 'upload') ids.add(activeRun.run_id);
    return ids;
  }, [activeRun, runs]);

  const dashboardRows = useMemo<DashboardQuizRow[]>(() => {
    if (quizGroups.length === 0) {
      return [
        {
          action: 'parse',
          actionLabel: 'Создать',
          errors: '-',
          name: 'Квизы не загружены',
          stage: 'Backend',
          status: 'Нет данных',
          tone: 'neutral',
        },
      ];
    }

    return quizGroups.slice(0, 5).map(rowFromQuizGroup);
  }, [quizGroups]);

  const isLocked = pipeline.status !== 'idle';
  const dashboardCurrentRun = isLocked ? undefined : toDashboardRun(activeRunSummary);
  const selectedQuizGroup = quizGroups.find((group) => group.id === selectedGroupId) ?? quizGroups[0] ?? null;
  const pipelineRunSummary = activeJobStatus.current === 'uploading'
    ? pipelineToRunSummary(pipeline, selectedQuizGroup, accountName(effectiveAccount))
    : null;
  const runsCurrentRun = pipelineRunSummary ?? activeRunSummary;
  const pipelineRunHasBackendRun = Boolean(pipelineRunSummary && pipelineRunSummary.id !== pipeline.activeJobId);
  const runsControlsEnabled = Boolean(
    pipelineRunSummary
      ? pipelineRunHasBackendRun
      : activeRunSummary && pausableRunIds.has(activeRunSummary.id),
  );
  const launchQuizCandidate: LaunchQuizCandidate | null = selectedQuizGroup
    ? {
        disabledReason:
          isLocked
            ? 'Дождитесь завершения текущей задачи.'
            : effectiveAccountStatus !== 'connected'
              ? 'Подключите аккаунт запуска перед стартом.'
              : selectedQuizGroup.status !== 'ready'
                ? 'Сначала проверьте JSON и исправьте ошибки в редакторе.'
                : undefined,
        id: selectedQuizGroup.id,
        name: selectedQuizGroup.name,
        questionCount: selectedQuizGroup.questions.length,
        status: selectedQuizGroup.status,
      }
    : null;

  const handleAccountChange = () => {
    if (accountOptions.length === 0) {
      setActiveRoute('accounts');
      return;
    }

    openModal('switch-account', {
      accounts: accountOptions,
      activeAccountId: effectiveAccount?.id,
      manageAccountsDisabled: false,
    });
  };

  const switchAccount = async (accountId: string) => {
    try {
      const nextAccount = await api.setCurrentAccount(accountId);
      setCurrentAccount(nextAccount);
      setAccounts((current) => (
        current.map((account) => ({ ...account, is_active: account.id === nextAccount.id }))
      ));
      closeModal();
      refreshAccounts();
    } catch (error) {
      console.error(error);
    }
  };

  const handleSetActiveAccount = (account: PublicAccountProfile) => {
    void switchAccount(account.id);
  };

  const showTelegramLoginError = (accountNameValue: string, error: unknown) => {
    const label = errorLabel(error);
    openModal('telegram-error', {
      accountName: accountNameValue,
      canOpenAccounts: true,
      canReconnect: false,
      canRetryLater: false,
      errorLabel: label,
      kind: 'unknown',
      recommendation: 'Проверьте профиль аккаунта и повторите вход.',
    });
    return label;
  };

  const handleStartLaunchQuiz = async (quiz: LaunchQuizCandidate, startFrom = 1) => {
    const group = quizGroups.find((item) => item.id === quiz.id);
    if (!group) return;

    if (group.status !== 'ready') {
      setSelectedGroupId(group.id);
      setActiveRoute('editor');
      return;
    }

    if (effectiveAccountStatus !== 'connected') {
      setActiveRoute('accounts');
      return;
    }

    try {
      const launchDefaults = effectiveSettings.defaultLaunch;
      await uploadGroup({
        contextMode: launchDefaults.contextMode,
        groupId: group.id,
        name: group.name,
        shuffleOptions: launchDefaults.shuffleOptions,
        speed: launchDefaults.speed,
        startFrom,
      });
    } catch (error) {
      showTelegramLoginError(accountName(effectiveAccount), error);
    }
  };

  const handleEnableAccount = async (account: PublicAccountProfile) => {
    const updated = await api.enableAccount(account.id);
    setAccounts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    if (updated.is_active) setCurrentAccount(updated);
    await refreshAccounts();
  };

  const handleDisableAccount = async (account: PublicAccountProfile) => {
    const updated = await api.disableAccount(account.id);
    setAccounts((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    if (updated.is_active) setCurrentAccount(updated);
    else if (currentAccount?.id === updated.id) setCurrentAccount(null);
    await refreshAccounts();
  };

  const handleDeleteAccount = async (account: PublicAccountProfile) => {
    const result = await api.deleteAccount(account.id);
    setAccounts((current) => current.filter((item) => item.id !== account.id));
    setCurrentAccount(result.active_account);
    if (telegramLogin?.profileId === account.id) setTelegramLogin(null);
    await refreshAccounts();
  };

  const completeTelegramLogin = async (account: AccountProfilePublic) => {
    setAccounts((current) => {
      const exists = current.some((item) => item.id === account.id);
      if (!exists) return [...current, account];
      return current.map((item) => (item.id === account.id ? account : item));
    });
    if (account.is_active) setCurrentAccount(account);
    setTelegramLogin(null);
    await refreshAccounts();
  };

  const handleStartTelegramLogin = async (
    account: PublicAccountProfile,
    options: { force?: boolean; forceSms?: boolean } = {},
  ) => {
    if (
      !options.force
      && (
        telegramLogin?.profileId === account.id
        && !telegramLogin.error
        && (telegramLogin.loading || telegramLogin.step === 'code_sent' || telegramLogin.step === 'password_required')
      )
    ) {
      setActiveRoute('accounts');
      return;
    }
    const requestId = telegramLoginRequest.current + 1;
    telegramLoginRequest.current = requestId;
    setActiveRoute('accounts');
    setTelegramLogin({
      accountName: account.name,
      loading: true,
      profileId: account.id,
      step: 'starting',
    });

    try {
      const response = await api.startTelegramLogin(account.id, {
        forceSms: options.forceSms,
      });
      if (telegramLoginRequest.current !== requestId) return;
      if (response.step === 'authorized') {
        await completeTelegramLogin(response.account);
        return;
      }
      setTelegramLogin({
        accountName: account.name,
        loading: false,
        loginId: response.login_id,
        phoneMasked: response.phone_masked,
        profileId: account.id,
        step: response.step,
      });
    } catch (error) {
      if (telegramLoginRequest.current !== requestId) return;
      const label = errorLabel(error);
      setTelegramLogin((current) => (
        current?.profileId === account.id
          ? { ...current, error: label, loading: false }
          : current
      ));
    }
  };

  const handleSubmitTelegramCode = async (code: string) => {
    if (!telegramLogin?.loginId) return;
    const currentLogin = telegramLogin;
    setTelegramLogin({ ...currentLogin, error: undefined, loading: true });

    try {
      const response = await api.submitTelegramCode(currentLogin.loginId, code);
      if (response.step === 'authorized') {
        await completeTelegramLogin(response.account);
        return;
      }
      setTelegramLogin({
        ...currentLogin,
        error: undefined,
        loading: false,
        step: 'password_required',
      });
    } catch (error) {
      const label = errorLabel(error);
      setTelegramLogin({ ...currentLogin, error: label, loading: false });
    }
  };

  const handleSubmitTelegramPassword = async (password: string) => {
    if (!telegramLogin?.loginId) return;
    const currentLogin = telegramLogin;
    setTelegramLogin({ ...currentLogin, error: undefined, loading: true });

    try {
      const response = await api.submitTelegramPassword(currentLogin.loginId, password);
      await completeTelegramLogin(response.account);
    } catch (error) {
      const label = errorLabel(error);
      setTelegramLogin({ ...currentLogin, error: label, loading: false });
    }
  };

  const handleRestartTelegramLogin = () => {
    if (!telegramLogin) return;
    const account = publicAccounts.find((item) => item.id === telegramLogin.profileId);
    if (!account) return;
    void handleStartTelegramLogin(account, { force: true });
  };

  const handleCancelTelegramLogin = async () => {
    telegramLoginRequest.current += 1;
    const loginId = telegramLogin?.loginId;
    setTelegramLogin(null);
    if (!loginId) return;
    try {
      await api.cancelTelegramLogin(loginId);
    } catch (error) {
      console.error(error);
    }
  };

  const handleDashboardQuizAction = (row: DashboardQuizRow, action: DashboardQuizAction) => {
    if (row.id) setSelectedGroupId(row.id);
    if (action === 'parse') setActiveRoute('create');
    if (action === 'launch' || action === 'remove') setActiveRoute('runs');
    if (action === 'fix' || action === 'edit' || action === 'open') setActiveRoute('editor');
  };

  const selectQuizAndOpen = (quiz: QuizListItem, routeId: AppRouteId) => {
    setSelectedGroupId(quiz.id);
    setActiveRoute(routeId);
  };

  const openArchiveDeleteQuiz = (quiz: QuizListItem, defaultAction: 'archive' | 'delete') => {
    const group = quizGroups.find((item) => item.id === quiz.id);
    const questionCount = group?.questions.length ?? (typeof quiz.questions === 'number' ? quiz.questions : 0);

    setArchiveDeleteError('');
    setArchiveDeleteSubmitting(false);
    openModal('archive-delete-quiz', {
      allowArchive: true,
      allowHardDelete: true,
      defaultAction,
      questionCount,
      quizId: quiz.id,
      quizTitle: group?.name ?? quiz.name,
    });
  };

  const confirmArchiveDeleteQuiz = async ({ quizId, action }: { quizId: string; action: 'archive' | 'delete' }) => {
    if (archiveDeleteSubmitting) return;
    setArchiveDeleteError('');
    setArchiveDeleteSubmitting(true);
    try {
      if (action === 'archive') await api.archiveGroup(quizId);
      else await api.deleteGroup(quizId);

      const nextGroups = quizGroups.filter((group) => group.id !== quizId);
      setQuizGroups(nextGroups);
      if (selectedGroupId === quizId) {
        setSelectedGroupId(nextGroups[0]?.id ?? '');
      }
      closeCurrentModal();
      await refreshGroups();
    } catch (error) {
      console.error(error);
      setArchiveDeleteError(errorLabel(error));
    } finally {
      setArchiveDeleteSubmitting(false);
    }
  };

  const handlePauseRun = async (run: RunSummary) => {
    const isCurrentPipelineRun = Boolean(pipelineRunSummary && pipelineRunSummary.id === run.id && pipelineRunHasBackendRun);
    if (!pausableRunIds.has(run.id) && !isCurrentPipelineRun) return;

    try {
      await api.pauseRun(run.id);
      await refreshRuns();
    } catch (error) {
      console.error(error);
    }
  };

  const handleResumeRun = async (run: RunSummary) => {
    const isCurrentPipelineRun = Boolean(pipelineRunSummary && pipelineRunSummary.id === run.id && pipelineRunHasBackendRun);
    if (!pausableRunIds.has(run.id) && !isCurrentPipelineRun) return;

    try {
      const response = await api.resumeRun(run.id);
      watchJob(response.job_id, 'uploading', run.quizTitle, 'runs');
    } catch (error) {
      console.error(error);
    }
  };

  const handleContinueRun = async (run: RunSummary, questionIndex: number) => {
    try {
      const launchDefaults = effectiveSettings.defaultLaunch;
      const response = await api.continueRun(run.id, questionIndex, {
        confirmSkipForward: questionIndex > (run.nextQuestionIndex ?? run.currentQuestion ?? 1),
        contextSendMode: launchDefaults.contextMode,
        shuffleOptions: launchDefaults.shuffleOptions,
        speed: launchDefaults.speed,
      });
      watchJob(response.job_id, 'uploading', run.quizTitle, 'runs');
    } catch (error) {
      console.error(error);
      throw error;
    }
  };

  const handleStopRun = (run: RunSummary) => {
    setStopError('');
    openModal('stop-run', {
      accountName: run.accountName,
      canStop: true,
      completedQuestions: run.completedQuestions ?? Math.round((run.progress / 100) * run.totalQuestions),
      quizTitle: run.quizTitle,
      runId: run.id,
      totalQuestions: run.totalQuestions,
    });
  };

  const handleUpdateRunAutoResume = async (run: RunSummary, enabled: boolean, delaySeconds: number) => {
    try {
      const updated = await api.updateRunAutoResume(run.id, { delaySeconds, enabled });
      setRuns((current) => current.map((item) => (
        item.kind === 'upload' && item.run_id === run.id ? updated : item
      )));
      if (activeRun.active && activeRun.kind === 'upload' && activeRun.run_id === run.id) {
        setActiveRun({ ...updated, active: true });
      }
    } catch (error) {
      console.error(error);
      throw error;
    }
  };

  const confirmStopRun = async (runId: string) => {
    setStoppingRunId(runId);
    setStopError('');
    try {
      if (pipeline.activeJobId === runId) {
        await api.cancelJob(runId);
      } else {
        await api.stopRun(runId);
      }
      setStoppingRunIds((current) => {
        const next = new Set(current);
        next.add(runId);
        return next;
      });
      closeCurrentModal();
      await refreshRuns();
    } catch (error) {
      console.error(error);
      const message = errorLabel(error);
      const alreadyTerminal =
        /already terminal/i.test(message) ||
        (error instanceof Error && /already terminal/i.test(error.message));
      if (alreadyTerminal) {
        // Фронт отстал от бэкенда: запуск уже завершён, но pipeline/SSE завис в
        // «uploading» и держит фантомный «текущий запуск» с активной кнопкой стопа.
        // Сбрасываем залипший pipeline (только если он про этот запуск), закрываем
        // модалку и синхронизируем список — без плашки, раз останавливать уже нечего.
        if (pipeline.activeJobId === runId || pipelineRunSummary?.id === runId) {
          activeJobStatus.current = 'idle';
          setPipeline(idlePipeline);
        }
        closeCurrentModal();
        await refreshRuns();
      } else {
        setStopError(message);
      }
    } finally {
      setStoppingRunId(null);
    }
  };

  const handleEditorExitRequest = (request: QuizEditorExitRequest) => {
    if (!request.hasUnsavedChanges) {
      request.proceed();
      return;
    }

    setPendingEditorExit(request);
    openModal('unsaved-changes', {
      canSave: false,
      changedQuestionsCount: 1,
      lastAutosaveLabel: 'ручное сохранение доступно в редакторе',
      quizTitle: selectedQuizGroup?.name ?? 'квиз',
    });
  };

  const discardEditorChanges = () => {
    pendingEditorExit?.proceed();
    setPendingEditorExit(null);
    closeModal();
  };

  const closeCurrentModal = () => {
    setPendingEditorExit(null);
    setArchiveDeleteError('');
    setArchiveDeleteSubmitting(false);
    setStopError('');
    closeModal();
  };

  const activeScreen = (() => {
    switch (activeRoute) {
      case 'create':
        return (
          <CreateQuizScreen
            initialValues={{
              workspaceDir: workspaceConfig.workspaceDir,
            }}
            jobError={pipeline.error}
            jobProgress={pipeline.progress}
            jobStep={pipeline.currentStep}
            onCancel={() => setActiveRoute('dashboard')}
            onCreateFromDocx={createQuizFromDocx}
            onCreateFromJson={createQuizFromJson}
            onCreateManual={createManualQuiz}
            status={pipeline.status}
          />
        );
      case 'editor':
        return (
          <QuizEditorScreen
            isLocked={isLocked}
            onReadyForLaunch={markEditorGroupReady}
            onRequestExit={handleEditorExitRequest}
            onSelectedGroupChange={setSelectedGroupId}
            onValidateJson={validateEditorGroup}
            quizGroup={selectedQuizGroup}
            quizGroups={quizGroups}
            resolveMediaUrl={mediaUrl}
            saveQuizGroup={saveEditorGroup}
            selectedGroupId={selectedGroupId}
            updateQuizGroup={saveEditorGroup}
            uploadMedia={uploadMedia}
          />
        );
      case 'quizzes':
        return (
          <QuizzesScreen
            onCreateQuiz={() => setActiveRoute('create')}
            onArchiveQuiz={(quiz) => openArchiveDeleteQuiz(quiz, 'archive')}
            onDeleteQuiz={(quiz) => openArchiveDeleteQuiz(quiz, 'delete')}
            onEditQuiz={(quiz) => selectQuizAndOpen(quiz, 'editor')}
            onLaunchQuiz={(quiz) => selectQuizAndOpen(quiz, 'runs')}
            onOpenQuiz={(quiz) => selectQuizAndOpen(quiz, 'editor')}
            onParseQuiz={() => setActiveRoute('create')}
            quizGroups={quizGroups}
          />
        );
      case 'runs':
        return (
          <RunsScreen
            controlsEnabled={runsControlsEnabled}
            currentRun={runsCurrentRun}
            currentRunStopping={Boolean(runsCurrentRun && stoppingRunIds.has(runsCurrentRun.id))}
            dangerousActionsEnabled={Boolean(runsCurrentRun)}
            launchQuiz={launchQuizCandidate}
            onStartLaunchQuiz={handleStartLaunchQuiz}
            onContinueRun={handleContinueRun}
            onPauseRun={handlePauseRun}
            onResumeRun={handleResumeRun}
            onStopRun={handleStopRun}
            onUpdateRunAutoResume={handleUpdateRunAutoResume}
            queueActionsEnabled={false}
            runs={runSummaries}
          />
        );
      case 'accounts':
        return (
          <AccountsScreen
            accounts={publicAccounts}
            connectionActionsEnabled
            onCancelTelegramLogin={handleCancelTelegramLogin}
            onConnectAccount={handleStartTelegramLogin}
            onDeleteAccount={handleDeleteAccount}
            onDisableAccount={handleDisableAccount}
            onEnableAccount={handleEnableAccount}
            onReconnectAccount={handleStartTelegramLogin}
            onRestartTelegramLogin={handleRestartTelegramLogin}
            onSetActiveAccount={handleSetActiveAccount}
            onSubmitTelegramCode={handleSubmitTelegramCode}
            onSubmitTelegramPassword={handleSubmitTelegramPassword}
            managementEnabled
            switchEnabled={publicAccounts.length > 0}
            telegramLogin={telegramLogin}
          />
        );
      case 'settings':
        return (
          <SettingsScreen
            onResetSettings={handleResetSettings}
            onSaveSettings={handleSaveSettings}
            saving={settingsSaving}
            settings={effectiveSettings}
            storageActionsEnabled={false}
          />
        );
      case 'dashboard':
      default:
        return (
          <DashboardScreen
            currentRun={dashboardCurrentRun}
            isLocked={isLocked}
            onCreateQuiz={() => setActiveRoute('create')}
            onEditQueue={() => setActiveRoute('runs')}
            onNavigate={setActiveRoute}
            onOpenEditor={selectedQuizGroup ? () => setActiveRoute('editor') : undefined}
            onOpenRuns={() => setActiveRoute('runs')}
            onQuizAction={handleDashboardQuizAction}
            pipeline={pipeline}
            rows={dashboardRows}
          />
        );
    }
  })();

  void cancelPipeline;

  return (
    <AppShell
      activeRoute={activeRoute}
      activeAccountName={accountName(effectiveAccount)}
      currentStep={pipeline.currentStep}
      isLocked={isLocked}
      onAccountChange={handleAccountChange}
      onNavigate={setActiveRoute}
    >
      {activeScreen}

      {modal.modalId === 'switch-account' && (
        <SwitchAccountModal
          isOpen
          onClose={closeCurrentModal}
          onConfirm={switchAccount}
          onManageAccounts={() => {
            closeCurrentModal();
            setActiveRoute('accounts');
          }}
          payload={modal.payload}
        />
      )}

      {modal.modalId === 'unsaved-changes' && (
        <UnsavedChangesModal
          isOpen
          onClose={closeCurrentModal}
          onDiscard={discardEditorChanges}
          onStay={closeCurrentModal}
          payload={modal.payload}
        />
      )}

      {modal.modalId === 'telegram-error' && (
        <TelegramErrorModal
          isOpen
          onClose={closeCurrentModal}
          onOpenAccounts={() => {
            closeCurrentModal();
            setActiveRoute('accounts');
          }}
          payload={modal.payload}
        />
      )}

      {modal.modalId === 'stop-run' && (
        <StopRunModal
          error={stopError}
          isOpen
          isStopping={stoppingRunId === modal.payload.runId}
          onClose={closeCurrentModal}
          onConfirm={confirmStopRun}
          payload={modal.payload}
        />
      )}

      {modal.modalId === 'archive-delete-quiz' && (
        <ArchiveDeleteQuizModal
          error={archiveDeleteError}
          isOpen
          isSubmitting={archiveDeleteSubmitting}
          onClose={closeCurrentModal}
          onConfirm={confirmArchiveDeleteQuiz}
          payload={modal.payload}
        />
      )}
    </AppShell>
  );
}
