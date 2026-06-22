import { ArrowRight, Loader2, PencilLine, Plus } from 'lucide-react';
import { useMemo } from 'react';
import type { AppRouteId } from '../app/routes';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';
import { Progress } from '../components/ui/Progress';
import type { PipelineState, QuizGroup } from '../types';

type BadgeTone = 'neutral' | 'pink' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

export type DashboardQuizAction = 'open' | 'launch' | 'remove' | 'fix' | 'parse' | 'edit';

export type DashboardQuizRow = {
  action?: DashboardQuizAction;
  actionLabel?: string;
  errors: number | string;
  id?: string;
  name: string;
  stage: string;
  status: string;
  tone?: BadgeTone;
};

export type DashboardQueueItem = string | {
  id?: string;
  questions?: number;
  status?: string;
  title: string;
};

export type DashboardRunSummary = {
  currentGroup?: string;
  currentStep?: string;
  eta?: number;
  progress?: number;
  status: 'idle' | 'running' | 'paused' | 'failed' | 'completed' | 'queued';
  title?: string;
};

export type DashboardScreenProps = {
  currentRun?: DashboardRunSummary;
  isLocked?: boolean;
  onCreateQuiz?: () => void;
  onEditQueue?: () => void;
  onNavigate?: (routeId: AppRouteId) => void;
  onOpenEditor?: () => void;
  onOpenRuns?: () => void;
  onQuizAction?: (row: DashboardQuizRow, action: DashboardQuizAction) => void;
  pipeline?: PipelineState;
  queueItems?: DashboardQueueItem[];
  quizGroups?: QuizGroup[];
  rows?: DashboardQuizRow[];
};

function countGroupIssues(group: QuizGroup): number {
  return group.questions.reduce(
    (total, question) => total + (question.warnings?.length ?? 0) + (question.quality_flags?.length ?? 0),
    0,
  );
}

function rowFromGroup(group: QuizGroup): DashboardQuizRow {
  const issues = countGroupIssues(group);

  if (group.status === 'ready') {
    return {
      id: group.id,
      name: group.name,
      stage: 'Готов к запуску',
      errors: issues,
      status: issues > 0 ? 'Есть предупреждения' : 'Готов',
      action: 'launch',
      actionLabel: 'Запустить',
      tone: issues > 0 ? 'warning' : 'success',
    };
  }

  if (group.status === 'review') {
    return {
      id: group.id,
      name: group.name,
      stage: 'Проверка JSON',
      errors: Math.max(issues, 1),
      status: 'Нужно исправить',
      action: 'fix',
      actionLabel: 'Исправить',
      tone: 'danger',
    };
  }

  return {
    id: group.id,
    name: group.name,
    stage: 'Черновик',
    errors: issues,
    status: 'В работе',
    action: 'edit',
    actionLabel: 'Открыть',
    tone: 'neutral',
  };
}

function getRows(rows?: DashboardQuizRow[], quizGroups?: QuizGroup[]): DashboardQuizRow[] {
  if (rows && rows.length > 0) return rows;
  if (quizGroups && quizGroups.length > 0) return quizGroups.slice(0, 5).map(rowFromGroup);
  return [];
}

function runFromProps(pipeline?: PipelineState, currentRun?: DashboardRunSummary, isLocked?: boolean): DashboardRunSummary {
  if (currentRun) return currentRun;

  if (pipeline && (isLocked || pipeline.status !== 'idle')) {
    return {
      currentGroup: pipeline.currentGroup,
      currentStep: pipeline.currentStep,
      eta: pipeline.eta,
      progress: pipeline.progress,
      status: 'running',
      title: pipeline.currentGroup || 'Фоновая задача',
    };
  }

  return { status: 'idle' };
}

function routeForAction(action: DashboardQuizAction): AppRouteId {
  if (action === 'parse') return 'create';
  if (action === 'launch' || action === 'remove') return 'runs';
  return 'editor';
}

function formatQueueItem(item: DashboardQueueItem): string {
  if (typeof item === 'string') return item;
  const suffix = item.status ? ` - ${item.status}` : '';
  const count = typeof item.questions === 'number' ? ` (${item.questions} вопр.)` : '';
  return `${item.title}${suffix}${count}`;
}

export default function DashboardScreen({
  currentRun,
  isLocked = false,
  onCreateQuiz,
  onEditQueue,
  onNavigate,
  onOpenEditor,
  onOpenRuns,
  onQuizAction,
  pipeline,
  queueItems,
  quizGroups,
  rows,
}: DashboardScreenProps) {
  const tableRows = useMemo(() => getRows(rows, quizGroups), [quizGroups, rows]);
  const queue = queueItems ?? [];
  const run = runFromProps(pipeline, currentRun, isLocked);
  const hasRun = run.status !== 'idle';

  const goTo = (routeId: AppRouteId) => onNavigate?.(routeId);

  const handleQuizAction = (row: DashboardQuizRow) => {
    const action = row.action ?? 'open';
    onQuizAction?.(row, action);
    goTo(routeForAction(action));
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Главная</h1>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel>
          <PanelHeader title="Быстрые действия" />
          <PanelBody className="space-y-4 pt-4">
            <div className="flex flex-wrap gap-4">
              <Button
                icon={<Plus className="size-5" aria-hidden="true" />}
                onClick={() => {
                  onCreateQuiz?.();
                  goTo('create');
                }}
                variant="primary"
              >
                Создать квиз
              </Button>
              {onOpenEditor && (
                <Button
                  icon={<PencilLine className="size-5" aria-hidden="true" />}
                  onClick={() => {
                    onOpenEditor();
                    goTo('editor');
                  }}
                >
                  Открыть редактор
                </Button>
              )}
            </div>
            <p className="text-sm leading-6 text-gray-600">
              Создайте квиз из документа или продолжите последний черновик.
            </p>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Текущий запуск" />
          <PanelBody className="space-y-4 pt-4">
            {hasRun ? (
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-[#FCE7F0] p-2 text-[#E85D8F]">
                    <Loader2 className="size-5 animate-spin" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-950">{run.title || run.currentGroup || 'Текущий запуск'}</p>
                    <p className="mt-1 truncate text-sm text-gray-500">{run.currentStep || 'Выполняется'}</p>
                    {typeof run.eta === 'number' && run.eta > 0 && (
                      <p className="mt-1 text-xs text-gray-500">Осталось примерно: {run.eta} сек.</p>
                    )}
                  </div>
                </div>
                <Progress label="Прогресс" value={run.progress ?? 0} />
              </div>
            ) : (
              <p className="text-base text-gray-700">Нет активного запуска</p>
            )}
            <Button
              icon={<ArrowRight className="size-4" aria-hidden="true" />}
              onClick={() => {
                onOpenRuns?.();
                goTo('runs');
              }}
            >
              Открыть запуски
            </Button>
          </PanelBody>
        </Panel>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel>
          <PanelHeader title="Последние квизы" />
          <PanelBody className="pt-4">
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full min-w-[640px] text-left text-sm xl:min-w-0">
                <thead className="bg-gray-50 text-gray-700">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Название</th>
                    <th className="px-4 py-3 font-semibold">Этап</th>
                    <th className="px-4 py-3 font-semibold">Ошибки</th>
                    <th className="px-4 py-3 font-semibold">Статус</th>
                    <th className="px-4 py-3 text-right font-semibold">Действие</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row) => (
                    <tr className="border-t border-gray-200" key={row.id ?? `${row.name}-${row.stage}`}>
                      <td className="px-4 py-3 font-medium text-gray-950">{row.name}</td>
                      <td className="px-4 py-3 text-gray-700">{row.stage}</td>
                      <td className="px-4 py-3 text-gray-700">{row.errors}</td>
                      <td className="px-4 py-3">
                        <Badge tone={row.tone ?? 'neutral'}>{row.status}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          className="font-semibold text-[#E85D8F] transition-colors hover:text-[#d94a7d] disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={() => handleQuizAction(row)}
                          type="button"
                        >
                          {row.actionLabel ?? 'Открыть'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Очередь" />
          <PanelBody className="flex min-h-[240px] flex-col justify-between gap-5 pt-4">
            <ol className="space-y-0 text-sm text-gray-900">
              {queue.map((item, index) => (
                <li className="border-b border-gray-200 py-4 last:border-b-0" key={typeof item === 'string' ? item : item.id ?? item.title}>
                  {index + 1}. {formatQueueItem(item)}
                </li>
              ))}
            </ol>
            <Button
              onClick={() => {
                onEditQueue?.();
                goTo('runs');
              }}
            >
              Изменить
            </Button>
          </PanelBody>
        </Panel>
      </div>
    </div>
  );
}
