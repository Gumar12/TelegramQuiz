import { Archive, ChevronRight, Plus, Search, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody } from '../components/ui/Panel';
import type { QuizGroup } from '../types';

type BadgeTone = 'neutral' | 'pink' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

export type QuizListStatus = 'running' | 'queued' | 'ready' | 'needs_fix' | 'needs_parse' | 'draft' | 'completed';
export type QuizListAction = 'open' | 'launch' | 'remove' | 'fix' | 'parse' | 'edit' | 'archive' | 'delete';
export type QuizFilter = 'all' | 'drafts' | 'errors' | 'ready' | 'queued' | 'completed';

export type QuizListItem = {
  errors?: number | string;
  id: string;
  name: string;
  primaryAction?: QuizListAction;
  primaryActionLabel?: string;
  questions?: number | string;
  status: QuizListStatus;
  updatedAt?: string;
};

export type QuizzesScreenProps = {
  filter?: QuizFilter;
  onArchiveQuiz?: (quiz: QuizListItem) => void;
  onCreateQuiz?: () => void;
  onDeleteQuiz?: (quiz: QuizListItem) => void;
  onEditQuiz?: (quiz: QuizListItem) => void;
  onFilterChange?: (filter: QuizFilter) => void;
  onLaunchQuiz?: (quiz: QuizListItem) => void;
  onOpenQuiz?: (quiz: QuizListItem) => void;
  onParseQuiz?: (quiz: QuizListItem) => void;
  onQuizAction?: (quiz: QuizListItem, action: QuizListAction) => void;
  onRemoveFromQueue?: (quiz: QuizListItem) => void;
  quizGroups?: QuizGroup[];
  quizzes?: QuizListItem[];
};

const filters: Array<{ id: QuizFilter; label: string }> = [
  { id: 'all', label: 'Все' },
  { id: 'drafts', label: 'Черновики' },
  { id: 'errors', label: 'С ошибками' },
  { id: 'ready', label: 'Готовые' },
  { id: 'queued', label: 'В очереди' },
  { id: 'completed', label: 'Завершённые' },
];

const statusMeta: Record<QuizListStatus, { label: string; tone: BadgeTone }> = {
  completed: { label: 'Завершён', tone: 'success' },
  draft: { label: 'Черновик', tone: 'neutral' },
  needs_fix: { label: 'Нужно исправить', tone: 'danger' },
  needs_parse: { label: 'Нужно парсить', tone: 'warning' },
  queued: { label: 'В очереди', tone: 'info' },
  ready: { label: 'Готов', tone: 'neutral' },
  running: { label: 'Выполняется', tone: 'success' },
};

function countGroupIssues(group: QuizGroup): number {
  return group.questions.reduce(
    (total, question) => total + (question.warnings?.length ?? 0) + (question.quality_flags?.length ?? 0),
    0,
  );
}

function itemFromGroup(group: QuizGroup): QuizListItem {
  const issues = countGroupIssues(group);

  if (group.status === 'ready') {
    return {
      id: group.id,
      name: group.name,
      questions: group.questions.length,
      errors: issues,
      status: 'ready',
      updatedAt: group.date || 'сегодня',
      primaryAction: 'launch',
      primaryActionLabel: 'Запустить',
    };
  }

  if (group.status === 'review') {
    return {
      id: group.id,
      name: group.name,
      questions: group.questions.length,
      errors: Math.max(issues, 1),
      status: 'needs_fix',
      updatedAt: group.date || 'сегодня',
      primaryAction: 'fix',
      primaryActionLabel: 'Исправить',
    };
  }

  return {
    id: group.id,
    name: group.name,
    questions: group.questions.length,
    errors: issues,
    status: 'draft',
    updatedAt: group.date || 'сегодня',
    primaryAction: 'edit',
    primaryActionLabel: 'Редактировать',
  };
}

function getQuizzes(quizzes?: QuizListItem[], quizGroups?: QuizGroup[]): QuizListItem[] {
  if (quizzes && quizzes.length > 0) return quizzes;
  if (quizGroups && quizGroups.length > 0) return quizGroups.map(itemFromGroup);
  return [];
}

function matchesFilter(item: QuizListItem, filter: QuizFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'drafts') return item.status === 'draft';
  if (filter === 'errors') return item.status === 'needs_fix' || Number(item.errors) > 0;
  if (filter === 'ready') return item.status === 'ready';
  if (filter === 'queued') return item.status === 'queued';
  return item.status === 'completed';
}

function defaultActionForStatus(status: QuizListStatus): QuizListAction {
  if (status === 'queued') return 'remove';
  if (status === 'ready') return 'launch';
  if (status === 'needs_fix') return 'fix';
  if (status === 'needs_parse') return 'parse';
  if (status === 'draft') return 'edit';
  return 'open';
}

function defaultActionLabel(action: QuizListAction): string {
  if (action === 'launch') return 'Запустить';
  if (action === 'remove') return 'Убрать';
  if (action === 'fix') return 'Исправить';
  if (action === 'parse') return 'Парсить';
  if (action === 'edit') return 'Редактировать';
  if (action === 'archive') return 'Архив';
  if (action === 'delete') return 'Удалить';
  return 'Открыть';
}

export default function QuizzesScreen({
  filter,
  onArchiveQuiz,
  onCreateQuiz,
  onDeleteQuiz,
  onEditQuiz,
  onFilterChange,
  onLaunchQuiz,
  onOpenQuiz,
  onParseQuiz,
  onQuizAction,
  onRemoveFromQueue,
  quizGroups,
  quizzes,
}: QuizzesScreenProps) {
  const [search, setSearch] = useState('');
  const [localFilter, setLocalFilter] = useState<QuizFilter>('all');
  const activeFilter = filter ?? localFilter;

  const sourceItems = useMemo(() => getQuizzes(quizzes, quizGroups), [quizGroups, quizzes]);
  const visibleItems = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return sourceItems.filter((item) => {
      const matchesSearch = normalizedSearch.length === 0 || item.name.toLowerCase().includes(normalizedSearch);
      return matchesSearch && matchesFilter(item, activeFilter);
    });
  }, [activeFilter, search, sourceItems]);

  const setFilter = (nextFilter: QuizFilter) => {
    setLocalFilter(nextFilter);
    onFilterChange?.(nextFilter);
  };

  const runAction = (quiz: QuizListItem, action: QuizListAction) => {
    onQuizAction?.(quiz, action);

    if (action === 'launch') onLaunchQuiz?.(quiz);
    else if (action === 'remove') onRemoveFromQueue?.(quiz);
    else if (action === 'fix' || action === 'edit') onEditQuiz?.(quiz);
    else if (action === 'parse') onParseQuiz?.(quiz);
    else if (action === 'archive') onArchiveQuiz?.(quiz);
    else if (action === 'delete') onDeleteQuiz?.(quiz);
    else onOpenQuiz?.(quiz);
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Квизы</h1>
        <Button icon={<Plus className="size-5" aria-hidden="true" />} onClick={onCreateQuiz} variant="primary">
          Новый квиз
        </Button>
      </div>

      <div className="space-y-4">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-gray-500" aria-hidden="true" />
          <input
            className="h-11 w-full rounded-lg border border-gray-200 bg-white pl-11 pr-4 text-sm text-gray-950 outline-none transition placeholder:text-gray-400 focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Найти квиз"
            type="search"
            value={search}
          />
        </label>

        <div className="flex flex-wrap gap-2">
          {filters.map((item) => {
            const isActive = item.id === activeFilter;
            return (
              <button
                className={[
                  'min-h-10 rounded-md border px-4 text-sm font-semibold transition-colors',
                  isActive
                    ? 'border-[#E85D8F] bg-[#FCE7F0] text-[#E85D8F]'
                    : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50',
                ].join(' ')}
                key={item.id}
                onClick={() => setFilter(item.id)}
                type="button"
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      <Panel>
        <PanelBody className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-white text-gray-700">
                <tr>
                  <th className="px-4 py-3 font-bold">Название</th>
                  <th className="px-4 py-3 font-bold">Вопросы</th>
                  <th className="px-4 py-3 font-bold">Ошибки</th>
                  <th className="px-4 py-3 font-bold">Статус</th>
                  <th className="px-4 py-3 font-bold">Обновлён</th>
                  <th className="px-4 py-3 text-right font-bold">Действие</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => {
                  const meta = statusMeta[item.status];
                  const action = item.primaryAction ?? defaultActionForStatus(item.status);
                  const actionLabel = item.primaryActionLabel ?? defaultActionLabel(action);
                  const hasErrors = Number(item.errors) > 0 || item.status === 'needs_fix';

                  return (
                    <tr className="border-b border-gray-200 last:border-b-0" key={item.id}>
                      <td className="px-4 py-3 font-bold text-gray-950">{item.name}</td>
                      <td className="px-4 py-3 text-gray-950">{item.questions ?? '-'}</td>
                      <td className={['px-4 py-3', hasErrors ? 'font-bold text-red-600' : 'text-gray-950'].join(' ')}>
                        {item.errors ?? '-'}
                      </td>
                      <td className="px-4 py-3">
                        <Badge className="gap-1.5" tone={meta.tone}>
                          <span className="size-2 rounded-full bg-current" aria-hidden="true" />
                          {meta.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{item.updatedAt ?? '-'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-4">
                          <button
                            className="font-semibold text-[#E85D8F] transition-colors hover:text-[#d94a7d]"
                            onClick={() => runAction(item, action)}
                            type="button"
                          >
                            {actionLabel}
                          </button>
                          {(onArchiveQuiz || onQuizAction) && (
                            <button
                              aria-label={`Архивировать ${item.name}`}
                              className="text-gray-400 transition-colors hover:text-[#E85D8F]"
                              onClick={() => runAction(item, 'archive')}
                              type="button"
                            >
                              <Archive className="size-4" aria-hidden="true" />
                            </button>
                          )}
                          {(onDeleteQuiz || onQuizAction) && (
                            <button
                              aria-label={`Удалить ${item.name}`}
                              className="text-gray-400 transition-colors hover:text-red-600"
                              onClick={() => runAction(item, 'delete')}
                              type="button"
                            >
                              <Trash2 className="size-4" aria-hidden="true" />
                            </button>
                          )}
                          <ChevronRight className="size-5 text-gray-500" aria-hidden="true" />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {visibleItems.length === 0 && (
              <div className="border-t border-gray-200 px-6 py-12 text-center text-gray-500">
                Квизы по этому фильтру не найдены.
              </div>
            )}
          </div>
        </PanelBody>
      </Panel>
    </div>
  );
}
