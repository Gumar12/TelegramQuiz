import { ArrowDown, ArrowUp, GripVertical, ListPlus, Rows3, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from '../../ui/Button';
import { Panel, PanelBody, PanelHeader } from '../../ui/Panel';
import { RunQueueStatusBadge } from './RunStatusBadge';
import type { RunQueueItem, RunQueueMoveDirection } from './types';

type RunQueuePanelProps = {
  actionsEnabled?: boolean;
  items: RunQueueItem[];
  onAddToQueue?: () => void;
  onEditQueue?: () => void;
  onMoveQueueItem?: (item: RunQueueItem, direction: RunQueueMoveDirection) => void;
  onRemoveQueueItem?: (item: RunQueueItem) => void;
};

export function RunQueuePanel({
  actionsEnabled = false,
  items,
  onAddToQueue,
  onEditQueue,
  onMoveQueueItem,
  onRemoveQueueItem,
}: RunQueuePanelProps) {
  const canAdd = actionsEnabled && Boolean(onAddToQueue);
  const canEdit = actionsEnabled && Boolean(onEditQueue);
  const canMove = actionsEnabled && Boolean(onMoveQueueItem);
  const canRemove = actionsEnabled && Boolean(onRemoveQueueItem);

  return (
    <Panel>
      <PanelHeader
        action={
          canEdit ? (
            <Button
              icon={<Rows3 className="size-4" aria-hidden="true" />}
              onClick={onEditQueue}
              size="sm"
            >
              Изменить
            </Button>
          ) : undefined
        }
        title="Очередь запусков"
      />
      <PanelBody className="space-y-4 pt-4">
        {canAdd && (
          <Button
            className="w-full"
            icon={<ListPlus className="size-5" aria-hidden="true" />}
            onClick={onAddToQueue}
            variant="outline"
          >
            Добавить в очередь
          </Button>
        )}

        {items.length > 0 ? (
          <ol className="overflow-hidden rounded-lg border border-gray-200">
            {items.map((item, index) => (
              <li className="flex items-center gap-3 border-b border-gray-200 px-4 py-3 last:border-b-0" key={item.id}>
                <GripVertical className="size-4 shrink-0 text-gray-400" aria-hidden="true" />
                <span className="w-5 shrink-0 text-sm font-semibold text-gray-500">{index + 1}.</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-semibold text-gray-950">{item.title}</span>
                    <RunQueueStatusBadge status={item.status} />
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
                    {typeof item.questionCount === 'number' ? `${item.questionCount} вопросов` : item.disabledReason ?? 'Готов к обработке'}
                  </p>
                </div>
                {(canMove || canRemove) && (
                  <div className="flex shrink-0 items-center gap-2">
                    {canMove && index > 0 && (
                      <IconButton
                        label={`Поднять ${item.title}`}
                        onClick={() => onMoveQueueItem?.(item, 'up')}
                      >
                        <ArrowUp className="size-4" aria-hidden="true" />
                      </IconButton>
                    )}
                    {canMove && index < items.length - 1 && (
                      <IconButton
                        label={`Опустить ${item.title}`}
                        onClick={() => onMoveQueueItem?.(item, 'down')}
                      >
                        <ArrowDown className="size-4" aria-hidden="true" />
                      </IconButton>
                    )}
                    {canRemove && (
                      <IconButton
                        label={`Убрать ${item.title}`}
                        onClick={() => onRemoveQueueItem?.(item)}
                      >
                        <X className="size-4" aria-hidden="true" />
                      </IconButton>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center">
            <p className="font-semibold text-gray-950">Очередь пуста</p>
            <p className="mt-2 text-sm leading-6 text-gray-500">Квизы появятся здесь после добавления в очередь.</p>
          </div>
        )}

        {actionsEnabled && <p className="text-xs leading-5 text-gray-500">Порядок меняется после подтверждения действия.</p>}
      </PanelBody>
    </Panel>
  );
}

function IconButton({
  children,
  label,
  onClick,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className="inline-flex size-8 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-950"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}
