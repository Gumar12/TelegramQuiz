import type { RunQueueItem, RunQueueMoveDirection, RunSummary } from '../components/domain/runs';
import { CurrentRunPanel, RunQueuePanel } from '../components/domain/runs';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';
import { ListPlus, Rocket, Rows3 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

export type LaunchQuizCandidate = {
  disabledReason?: string;
  id: string;
  name: string;
  questionCount: number;
  status: 'draft' | 'review' | 'ready' | string;
};

export type RunsScreenProps = {
  controlsEnabled?: boolean;
  currentRun?: RunSummary | null;
  currentRunStopping?: boolean;
  dangerousActionsEnabled?: boolean;
  launchQuiz?: LaunchQuizCandidate | null;
  onAddToQueue?: () => void;
  onContinueRun?: (run: RunSummary, questionIndex: number) => void;
  onEditQueue?: () => void;
  onMoveQueueItem?: (item: RunQueueItem, direction: RunQueueMoveDirection) => void;
  onObserveRun?: (run: RunSummary) => void;
  onOpenReport?: (run: RunSummary) => void;
  onOpenRun?: (run: RunSummary) => void;
  onPauseRun?: (run: RunSummary) => void;
  onRemoveQueueItem?: (item: RunQueueItem) => void;
  onResumeRun?: (run: RunSummary) => void;
  onRollbackRun?: (run: RunSummary, questionIndex: number) => void;
  onStartLaunchQuiz?: (quiz: LaunchQuizCandidate, startFrom: number) => void;
  onStopRun?: (run: RunSummary) => void;
  onUpdateRunAutoResume?: (run: RunSummary, enabled: boolean, delaySeconds: number) => Promise<void> | void;
  queueActionsEnabled?: boolean;
  queueItems?: RunQueueItem[];
  runs?: RunSummary[];
};

export default function RunsScreen({
  controlsEnabled = false,
  currentRun = null,
  currentRunStopping = false,
  dangerousActionsEnabled = false,
  launchQuiz = null,
  onAddToQueue,
  onContinueRun,
  onEditQueue,
  onMoveQueueItem,
  onObserveRun,
  onPauseRun,
  onRemoveQueueItem,
  onResumeRun,
  onRollbackRun,
  onStartLaunchQuiz,
  onStopRun,
  onUpdateRunAutoResume,
  queueActionsEnabled = false,
  queueItems = [],
}: RunsScreenProps) {
  const [startFromInput, setStartFromInput] = useState('1');
  const canAddToQueue = queueActionsEnabled && Boolean(onAddToQueue);
  const canEditQueue = queueActionsEnabled && Boolean(onEditQueue);
  const hasQuickActions = canAddToQueue || canEditQueue;
  const actionBlockedByTask = launchQuiz?.disabledReason === 'Дождитесь завершения текущей задачи.';
  const canClickLaunchQuiz = Boolean(launchQuiz && onStartLaunchQuiz && !actionBlockedByTask);
  const maxStartQuestion = Math.max(1, launchQuiz?.questionCount ?? 1);
  const startFrom = useMemo(() => {
    const parsed = Number(startFromInput);
    if (!Number.isFinite(parsed)) return 1;
    return Math.min(maxStartQuestion, Math.max(1, Math.floor(parsed)));
  }, [maxStartQuestion, startFromInput]);
  const launchButtonLabel = actionBlockedByTask
    ? 'Задача выполняется'
    : launchQuiz?.status !== 'ready'
      ? 'Открыть редактор'
        : launchQuiz?.disabledReason
          ? 'Подключить аккаунт'
          : 'Запустить новый квиз';

  useEffect(() => {
    setStartFromInput('1');
  }, [launchQuiz?.id, launchQuiz?.questionCount]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Запуски</h1>
        <p className="text-sm leading-6 text-gray-600">Текущий запуск и очередь.</p>
      </div>

      {launchQuiz && (
        <Panel className="border-[#F7B8D0] bg-[#FFF7FA]">
          <PanelBody className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#FCE7F0] text-[#E85D8F]">
                <Rocket className="size-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[#B83268]">Выбран для нового запуска</p>
                <h2 className="mt-1 truncate text-xl font-bold tracking-normal text-gray-950">{launchQuiz.name}</h2>
                <p className="mt-1 text-sm text-gray-600">
                  {launchQuiz.questionCount} вопросов · {launchQuiz.status === 'ready' ? 'готов к запуску' : 'нужна проверка'}
                </p>
                {launchQuiz.disabledReason && <p className="mt-2 text-sm font-semibold text-red-600">{launchQuiz.disabledReason}</p>}
              </div>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-[280px]">
              <label className="text-sm font-semibold text-gray-700" htmlFor="launch-start-from">
                Начать с вопроса
              </label>
              <div className="flex flex-col gap-3 sm:flex-row">
                <input
                  className="min-h-10 w-full rounded-md border border-gray-200 px-3 text-sm font-semibold text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0] sm:w-24"
                  disabled={!launchQuiz || launchQuiz.questionCount < 1}
                  id="launch-start-from"
                  inputMode="numeric"
                  max={maxStartQuestion}
                  min={1}
                  onBlur={() => setStartFromInput(String(startFrom))}
                  onChange={(event) => setStartFromInput(event.target.value)}
                  type="number"
                  value={startFromInput}
                />
                <Button
                  className="w-full sm:w-auto"
                  disabled={!canClickLaunchQuiz}
                  icon={<Rocket className="size-4" aria-hidden="true" />}
                  onClick={() => launchQuiz && onStartLaunchQuiz?.(launchQuiz, startFrom)}
                  variant="primary"
                >
                  {launchButtonLabel}
                </Button>
              </div>
              {launchQuiz && (
                <p className="text-sm text-gray-500">
                  Доступно: 1-{maxStartQuestion}
                </p>
              )}
            </div>
          </PanelBody>
        </Panel>
      )}

      <div className={hasQuickActions ? 'grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]' : 'grid gap-5'}>
        <CurrentRunPanel
          controlsEnabled={controlsEnabled}
          dangerousActionsEnabled={dangerousActionsEnabled}
          isStopping={currentRunStopping}
          onContinueRun={onContinueRun}
          onObserveRun={onObserveRun}
          onPauseRun={onPauseRun}
          onResumeRun={onResumeRun}
          onRollbackRun={onRollbackRun}
          onStopRun={onStopRun}
          onUpdateAutoResume={onUpdateRunAutoResume}
          run={currentRun}
        />

        {hasQuickActions && (
          <Panel>
            <PanelHeader title="Быстрое действие" />
            <PanelBody className="space-y-4 pt-4">
              {canAddToQueue && (
                <Button
                  className="w-full"
                  icon={<ListPlus className="size-5" aria-hidden="true" />}
                  onClick={onAddToQueue}
                  variant="outline"
                >
                  Добавить в очередь
                </Button>
              )}
              {canEditQueue && (
                <Button
                  className="w-full"
                  icon={<Rows3 className="size-5" aria-hidden="true" />}
                  onClick={onEditQueue}
                  variant="outline"
                >
                  Изменить очередь
                </Button>
              )}
            </PanelBody>
          </Panel>
        )}
      </div>

      <div className="grid gap-5">
        <RunQueuePanel
          actionsEnabled={queueActionsEnabled}
          items={queueItems}
          onAddToQueue={onAddToQueue}
          onEditQueue={onEditQueue}
          onMoveQueueItem={onMoveQueueItem}
          onRemoveQueueItem={onRemoveQueueItem}
        />
      </div>
    </div>
  );
}

export type { RunQueueItem, RunQueueMoveDirection, RunSummary };
