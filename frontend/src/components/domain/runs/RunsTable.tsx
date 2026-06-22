import { FileText, FolderOpen, PlayCircle, RotateCcw, Undo2 } from 'lucide-react';
import { Button } from '../../ui/Button';
import { Panel, PanelBody, PanelHeader } from '../../ui/Panel';
import { Progress } from '../../ui/Progress';
import { RunStatusBadge } from './RunStatusBadge';
import type { RunSummary } from './types';

type RunsTableProps = {
  controlsEnabled?: boolean;
  dangerousActionsEnabled?: boolean;
  onContinueRun?: (run: RunSummary, questionIndex: number) => void;
  onOpenReport?: (run: RunSummary) => void;
  onOpenRun?: (run: RunSummary) => void;
  onResumeRun?: (run: RunSummary) => void;
  onRollbackRun?: (run: RunSummary, questionIndex: number) => void;
  runs: RunSummary[];
};

function progressLabel(run: RunSummary) {
  const current = run.completedQuestions ?? run.currentQuestion ?? run.nextQuestionIndex;
  if (typeof current === 'number' && run.totalQuestions > 0) return `${current}/${run.totalQuestions}`;
  return `${Math.max(0, Math.min(100, Math.round(run.progress)))}%`;
}

function formatCompactEta(seconds: number | undefined) {
  if (typeof seconds !== 'number' || seconds <= 0) return '';
  const rounded = Math.max(0, Math.round(seconds));
  if (rounded < 60) return '~ <1 мин';
  const minutes = Math.round(rounded / 60);
  if (minutes < 60) return `~ ${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes > 0 ? `~ ${hours} ч ${restMinutes} мин` : `~ ${hours} ч`;
}

function canContinueStatus(status: RunSummary['status']) {
  return status === 'paused' || status === 'failed' || status === 'blocked' || status === 'cancelled';
}

export function RunsTable({
  controlsEnabled = false,
  dangerousActionsEnabled = false,
  onContinueRun,
  onOpenReport,
  onOpenRun,
  onResumeRun,
  onRollbackRun,
  runs,
}: RunsTableProps) {
  return (
    <Panel>
      <PanelHeader title="Последние запуски" />
      <PanelBody className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-sm">
            <thead className="border-b border-gray-200 bg-white text-gray-700">
              <tr>
                <th className="px-5 py-4 font-bold">Квиз</th>
                <th className="px-5 py-4 font-bold">Статус</th>
                <th className="px-5 py-4 font-bold">Аккаунт</th>
                <th className="px-5 py-4 font-bold">Прогресс</th>
                <th className="px-5 py-4 font-bold">Время</th>
                <th className="px-5 py-4 text-right font-bold">Действие</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const continueFrom = run.continueFrom ?? run.nextQuestionIndex ?? run.currentQuestion ?? 1;
                const rollbackTo = run.rollbackTo ?? Math.max(1, continueFrom - 1);
                const canOpen = Boolean(onOpenRun);
                const canReport = run.status === 'completed' && Boolean(onOpenReport);
                const canResume = controlsEnabled && run.status === 'paused' && Boolean(onResumeRun);
                const canContinue = dangerousActionsEnabled && canContinueStatus(run.status) && Boolean(onContinueRun);
                const canRollback = dangerousActionsEnabled && Boolean(onRollbackRun);
                const etaLabel = formatCompactEta(run.estimatedRemainingSeconds);

                return (
                  <tr className="border-b border-gray-200 last:border-b-0" key={run.id}>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[#FCE7F0] text-[#E85D8F]">
                          <FileText className="size-4" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-gray-950">{run.quizTitle}</div>
                          <div className="mt-1 text-xs text-gray-500">{run.id}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="px-5 py-4 text-gray-700">{run.accountName}</td>
                    <td className="px-5 py-4">
                      <div className="w-36">
                        <Progress label={progressLabel(run)} value={run.progress} />
                        {etaLabel && (
                          <div className="mt-1 text-xs font-semibold text-[#B83268]">{etaLabel}</div>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-4 text-gray-600">{run.updatedAt ?? run.startedAt ?? '-'}</td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        {canOpen && (
                          <Button
                            icon={<FolderOpen className="size-4" aria-hidden="true" />}
                            onClick={() => onOpenRun?.(run)}
                            size="sm"
                            variant="outline"
                          >
                            Открыть
                          </Button>
                        )}
                        {canReport && (
                          <Button
                            icon={<FileText className="size-4" aria-hidden="true" />}
                            onClick={() => onOpenReport?.(run)}
                            size="sm"
                            variant="outline"
                          >
                            Отчет
                          </Button>
                        )}
                        {canResume && (
                          <Button
                            icon={<PlayCircle className="size-4" aria-hidden="true" />}
                            onClick={() => onResumeRun?.(run)}
                            size="sm"
                            variant="outline"
                          >
                            Возобновить
                          </Button>
                        )}
                        {canContinue && (
                          <Button
                            icon={<RotateCcw className="size-4" aria-hidden="true" />}
                            onClick={() => onContinueRun?.(run, continueFrom)}
                            size="sm"
                            variant="outline"
                          >
                            С {continueFrom}
                          </Button>
                        )}
                        {canRollback && (
                          <Button
                            icon={<Undo2 className="size-4" aria-hidden="true" />}
                            onClick={() => onRollbackRun?.(run, rollbackTo)}
                            size="sm"
                            variant="danger"
                          >
                            Откат
                          </Button>
                        )}
                        {!canOpen && !canReport && !canResume && !canContinue && !canRollback && (
                          <span className="text-sm text-gray-400">-</span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {runs.length === 0 && (
            <div className="border-t border-gray-200 px-6 py-12 text-center text-gray-500">
              История запусков появится после первого запуска.
            </div>
          )}
        </div>
      </PanelBody>
    </Panel>
  );
}
