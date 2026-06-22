import { Eye, PauseCircle, PlayCircle, RotateCcw, Square, Undo2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Badge } from '../../ui/Badge';
import { Button } from '../../ui/Button';
import { Panel, PanelBody, PanelHeader } from '../../ui/Panel';
import { Progress } from '../../ui/Progress';
import { RunStatusBadge } from './RunStatusBadge';
import type { RunSummary } from './types';

type CurrentRunPanelProps = {
  controlsEnabled?: boolean;
  dangerousActionsEnabled?: boolean;
  onContinueRun?: (run: RunSummary, questionIndex: number) => Promise<void> | void;
  onObserveRun?: (run: RunSummary) => void;
  onPauseRun?: (run: RunSummary) => void;
  onResumeRun?: (run: RunSummary) => void;
  onRollbackRun?: (run: RunSummary, questionIndex: number) => void;
  onStopRun?: (run: RunSummary) => void;
  onUpdateAutoResume?: (run: RunSummary, enabled: boolean, delaySeconds: number) => Promise<void> | void;
  run?: RunSummary | null;
};

function clampProgress(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function formatRunMeta(run: RunSummary) {
  const parts: string[] = [];
  if (typeof run.participantsTotal === 'number') parts.push(`${run.participantsTotal} участников`);
  if (typeof run.participantsCompleted === 'number') parts.push(`${run.participantsCompleted} завершили`);
  if (typeof run.participantsActive === 'number') parts.push(`${run.participantsActive} проходят`);
  return parts.length > 0 ? parts.join(' · ') : `Аккаунт: ${run.accountName}`;
}

function getQuestionLabel(run: RunSummary) {
  if (typeof run.completedQuestions === 'number' && run.totalQuestions > 0) {
    const uploadedLabel = `Загружено ${run.completedQuestions} из ${run.totalQuestions}`;
    if (
      run.status === 'running' &&
      typeof run.currentQuestion === 'number' &&
      run.currentQuestion <= run.totalQuestions
    ) {
      return `${uploadedLabel} · сейчас вопрос ${run.currentQuestion}`;
    }
    return uploadedLabel;
  }

  if (typeof run.currentQuestion === 'number' && run.totalQuestions > 0) {
    return `Вопрос ${run.currentQuestion} из ${run.totalQuestions}`;
  }

  if (typeof run.nextQuestionIndex === 'number') {
    return `Следующий вопрос: ${run.nextQuestionIndex}`;
  }

  return 'Прогресс сохранен на backend-стороне.';
}

function formatDuration(seconds: number) {
  const value = Math.max(0, Math.round(seconds));
  if (value < 60) return 'меньше минуты';
  const minutes = Math.round(value / 60);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  if (restMinutes === 0) return `${hours} ч`;
  return `${hours} ч ${restMinutes} мин`;
}

function getRemainingLabel(run: RunSummary) {
  if (
    run.status !== 'running'
    && run.status !== 'cooldown'
    && run.status !== 'queued'
  ) {
    return '';
  }
  if (typeof run.estimatedRemainingSeconds !== 'number' || run.estimatedRemainingSeconds <= 0) {
    return '';
  }
  return `Осталось примерно ${formatDuration(run.estimatedRemainingSeconds)}`;
}

function formatDateTime(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: '2-digit',
  });
}

function messageFromError(error: unknown): string {
  if (!(error instanceof Error)) return 'Не удалось продолжить запуск.';
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    // Keep plain error messages as-is.
  }
  return error.message || 'Не удалось продолжить запуск.';
}

export function CurrentRunPanel({
  controlsEnabled = false,
  dangerousActionsEnabled = false,
  onContinueRun,
  onObserveRun,
  onPauseRun,
  onResumeRun,
  onRollbackRun,
  onStopRun,
  onUpdateAutoResume,
  run,
}: CurrentRunPanelProps) {
  const initialContinueFrom = run?.continueFrom ?? run?.nextQuestionIndex ?? run?.currentQuestion ?? 1;
  const [continueInput, setContinueInput] = useState(String(initialContinueFrom));
  const [continueBusy, setContinueBusy] = useState(false);
  const [continueError, setContinueError] = useState('');
  const initialAutoResumeDelayMinutes = Math.max(1, Math.round((run?.autoResumeDelaySeconds ?? 300) / 60));
  const [autoResumeMinutes, setAutoResumeMinutes] = useState(String(initialAutoResumeDelayMinutes));
  const [autoResumeBusy, setAutoResumeBusy] = useState(false);
  const [autoResumeError, setAutoResumeError] = useState('');

  useEffect(() => {
    setContinueInput(String(initialContinueFrom));
    setContinueError('');
  }, [initialContinueFrom, run?.id]);

  useEffect(() => {
    setAutoResumeMinutes(String(initialAutoResumeDelayMinutes));
    setAutoResumeError('');
  }, [initialAutoResumeDelayMinutes, run?.id]);

  if (!run) {
    return (
      <Panel>
        <PanelHeader title="Текущий запуск" />
        <PanelBody>
          <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-5 py-8 text-center">
            <p className="text-base font-semibold text-gray-950">Нет активного запуска</p>
            <p className="mt-2 text-sm leading-6 text-gray-500">
              Когда появится активный запуск, здесь будут прогресс и доступные действия.
            </p>
          </div>
        </PanelBody>
      </Panel>
    );
  }

  const progress = clampProgress(run.progress);
  const rollbackTo = run.rollbackTo ?? Math.max(1, (run.nextQuestionIndex ?? run.currentQuestion ?? 1) - 1);
  const continueFrom = initialContinueFrom;
  const continueMin = Math.max(1, continueFrom);
  const continueMax = Math.max(continueMin, run.totalQuestions);
  const currentIndex = run.nextQuestionIndex ?? run.currentQuestion ?? 1;
  const canObserve = Boolean(onObserveRun);
  const canPause = controlsEnabled && run.status === 'running' && Boolean(onPauseRun);
  const canResume = controlsEnabled && (run.status === 'paused' || run.status === 'cooldown') && Boolean(onResumeRun);
  const canContinue =
    dangerousActionsEnabled &&
    (run.status === 'paused' || run.status === 'cooldown' || run.status === 'failed' || run.status === 'blocked' || run.status === 'cancelled') &&
    Boolean(onContinueRun);
  const canRollback = dangerousActionsEnabled && currentIndex > 1 && Boolean(onRollbackRun);
  const canStop = dangerousActionsEnabled && (run.status === 'running' || run.status === 'paused' || run.status === 'cooldown') && Boolean(onStopRun);
  const hasActions = canObserve || canPause || canResume || canContinue || canRollback || canStop;
  const continueQuestionIndex = Math.max(continueMin, Math.min(continueMax, Number(continueInput) || continueMin));
  const canSubmitContinue = canContinue && !continueBusy;
  const remainingLabel = getRemainingLabel(run);
  const autoResumeDelaySeconds = Math.max(60, Math.min(3600, Math.round((Number(autoResumeMinutes) || 5) * 60)));
  const autoResumeNextLabel = formatDateTime(run.autoResumeNextAt);

  const submitContinue = async () => {
    if (!canSubmitContinue) return;
    setContinueBusy(true);
    setContinueError('');
    try {
      await onContinueRun?.(run, continueQuestionIndex);
    } catch (error) {
      setContinueError(messageFromError(error));
    } finally {
      setContinueBusy(false);
    }
  };

  const updateAutoResume = async (enabled: boolean, delaySeconds = autoResumeDelaySeconds) => {
    if (!onUpdateAutoResume || autoResumeBusy) return;
    setAutoResumeBusy(true);
    setAutoResumeError('');
    try {
      await onUpdateAutoResume(run, enabled, delaySeconds);
    } catch (error) {
      setAutoResumeError(messageFromError(error));
    } finally {
      setAutoResumeBusy(false);
    }
  };

  return (
    <Panel>
      <PanelHeader title="Текущий запуск" />
      <PanelBody className="space-y-4 pt-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-[#FCE7F0] text-[#E85D8F]">
              <PlayCircle className="size-6" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-xl font-bold tracking-normal text-gray-950">{run.quizTitle}</h2>
                <RunStatusBadge status={run.status} />
              </div>
              <p className="mt-1.5 text-sm leading-6 text-gray-600">{formatRunMeta(run)}</p>
              {run.lastError && (
                <Badge className="mt-2 max-w-full whitespace-normal" tone="danger">
                  {run.lastError}
                </Badge>
              )}
            </div>
          </div>
          <div className="text-left text-sm text-gray-500 sm:text-right">
            <div>{run.updatedAt ?? run.startedAt ?? 'Время не передано'}</div>
            <div className="mt-1 font-semibold text-gray-700">{run.id}</div>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_52px] sm:items-end">
          <Progress label={getQuestionLabel(run)} value={progress} />
          <div className="text-right text-base font-bold text-gray-950">{progress}%</div>
        </div>
        {remainingLabel && (
          <div className="rounded-md border border-pink-100 bg-pink-50 px-3 py-2 text-sm font-semibold text-[#B83268]">
            {remainingLabel}
          </div>
        )}

        {onUpdateAutoResume && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3">
                <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-white text-[#E85D8F]">
                  <RotateCcw className="size-5" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="font-semibold text-gray-950">Автопродолжение при сбое</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">
                    Повторит запуск после технической остановки. Ручная пауза и стоп не перезапускаются.
                  </p>
                  {run.autoResumeEnabled && autoResumeNextLabel && (
                    <p className="mt-1 text-sm font-semibold text-[#B83268]">
                      Следующая попытка: {autoResumeNextLabel}
                    </p>
                  )}
                  {typeof run.autoResumeAttempts === 'number' && run.autoResumeAttempts > 0 && (
                    <p className="mt-1 text-xs text-gray-500">Попыток автопродолжения: {run.autoResumeAttempts}</p>
                  )}
                </div>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="block space-y-1.5">
                  <span className="text-sm font-semibold text-gray-700">Через, мин</span>
                  <input
                    className="min-h-9 w-24 rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
                    disabled={autoResumeBusy}
                    max={60}
                    min={1}
                    onBlur={() => {
                      if (run.autoResumeEnabled) void updateAutoResume(true);
                    }}
                    onChange={(event) => setAutoResumeMinutes(event.target.value)}
                    type="number"
                    value={autoResumeMinutes}
                  />
                </label>
                <button
                  aria-checked={Boolean(run.autoResumeEnabled)}
                  className={`relative h-7 w-12 rounded-full border transition ${
                    run.autoResumeEnabled
                      ? 'border-[#E85D8F] bg-[#E85D8F]'
                      : 'border-gray-300 bg-gray-200'
                  } ${autoResumeBusy ? 'opacity-60' : ''}`}
                  disabled={autoResumeBusy}
                  onClick={() => void updateAutoResume(!run.autoResumeEnabled)}
                  role="switch"
                  type="button"
                >
                  <span
                    className={`absolute top-1 size-5 rounded-full bg-white shadow-sm transition ${
                      run.autoResumeEnabled ? 'left-6' : 'left-1'
                    }`}
                  />
                </button>
              </div>
            </div>
            {autoResumeError && (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
                {autoResumeError}
              </div>
            )}
          </div>
        )}

        {canContinue && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px_auto] sm:items-end">
              <label className="block space-y-1.5">
                <span className="text-sm font-semibold text-gray-700">Продолжить с вопроса</span>
                <input
                  className="min-h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
                  max={continueMax}
                  min={continueMin}
                  onChange={(event) => setContinueInput(event.target.value)}
                  type="number"
                  value={continueInput}
                />
              </label>
              <div className="text-sm leading-6 text-gray-500">
                Доступно: {continueMin}-{continueMax}
                {continueQuestionIndex > continueFrom && (
                  <span className="block text-amber-700">Вопросы до {continueQuestionIndex} будут пропущены.</span>
                )}
              </div>
              <Button
                disabled={!canSubmitContinue}
                loading={continueBusy}
                onClick={submitContinue}
                variant="primary"
              >
                Продолжить
              </Button>
            </div>
            {continueError && (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
                {continueError}
              </div>
            )}
          </div>
        )}

        {hasActions && (
          <div className="flex flex-wrap gap-2">
            {canObserve && (
              <Button
                icon={<Eye className="size-4" aria-hidden="true" />}
                onClick={() => onObserveRun?.(run)}
                size="sm"
                variant="primary"
              >
                Наблюдать
              </Button>
            )}
            {canPause && (
              <Button
                icon={<PauseCircle className="size-4" aria-hidden="true" />}
                onClick={() => onPauseRun?.(run)}
                size="sm"
              >
                Пауза
              </Button>
            )}
            {canResume && (
              <Button
                icon={<PlayCircle className="size-4" aria-hidden="true" />}
                onClick={() => onResumeRun?.(run)}
                size="sm"
              >
                Возобновить
              </Button>
            )}
            {canRollback && (
              <Button
                icon={<Undo2 className="size-4" aria-hidden="true" />}
                onClick={() => onRollbackRun?.(run, rollbackTo)}
                size="sm"
                variant="danger"
              >
                Откат к {rollbackTo}
              </Button>
            )}
            {canStop && (
              <Button
                icon={<Square className="size-4" aria-hidden="true" />}
                onClick={() => onStopRun?.(run)}
                size="sm"
                variant="danger"
              >
                Остановить
              </Button>
            )}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
