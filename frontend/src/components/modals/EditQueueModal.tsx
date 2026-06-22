import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, GripVertical, Plus, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import type { EditQueueModalPayload, QueueItem } from '../../state/modalStore';
import { Notice, QueueStatusBadge } from './ModalBlocks';

type QueueOrderChange = {
  id: string;
  position: number;
};

type EditQueueModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: EditQueueModalPayload;
  onAddQuiz?: () => void;
  onSaveOrder?: (items: QueueOrderChange[]) => void;
};

function moveItem(items: QueueItem[], fromIndex: number, toIndex: number) {
  const next = [...items];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next;
}

export function EditQueueModal({ isOpen, onAddQuiz, onClose, onSaveOrder, payload }: EditQueueModalProps) {
  const [items, setItems] = useState(payload.items);

  useEffect(() => {
    setItems(payload.items);
  }, [payload.items]);

  const saveDisabled = payload.canSaveOrder !== true || !onSaveOrder;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Изменить очередь"
      footer={
        <>
          <Button
            className="mr-auto"
            disabled={payload.canAddQuiz !== true || !onAddQuiz}
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={onAddQuiz}
            variant="outline"
          >
            Добавить квиз
          </Button>
          <Button onClick={onClose} variant="outline">
            Отмена
          </Button>
          <Button
            disabled={saveDisabled}
            onClick={() => onSaveOrder?.(items.map((item, index) => ({ id: item.id, position: index + 1 })))}
            variant="primary"
          >
            Сохранить порядок
          </Button>
        </>
      }
    >
      <p className="mb-4 text-sm leading-6 text-gray-500">Перетащите квизы или используйте кнопки порядка.</p>

      <div className="mb-4 max-h-80 space-y-2 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-2">
        {items.map((item, index) => (
          <div className="flex items-center gap-3 rounded-md border border-gray-200 bg-white px-3 py-3" key={item.id}>
            <GripVertical className="size-4 shrink-0 text-gray-400" aria-hidden="true" />
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-gray-100 text-xs font-bold text-gray-600">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold text-gray-950">{item.title}</div>
              {item.questionCount !== undefined && (
                <div className="text-xs text-gray-500">{item.questionCount} вопросов</div>
              )}
            </div>
            <QueueStatusBadge status={item.status} />
            <div className="flex shrink-0 items-center gap-1">
              <button
                aria-label="Поднять выше"
                className="inline-flex size-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={index === 0}
                onClick={() => setItems((current) => moveItem(current, index, index - 1))}
                type="button"
              >
                <ChevronUp className="size-4" aria-hidden="true" />
              </button>
              <button
                aria-label="Опустить ниже"
                className="inline-flex size-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={index === items.length - 1}
                onClick={() => setItems((current) => moveItem(current, index, index + 1))}
                type="button"
              >
                <ChevronDown className="size-4" aria-hidden="true" />
              </button>
              <button
                aria-label="Убрать из очереди"
                className="inline-flex size-8 items-center justify-center rounded-md text-red-500 hover:bg-red-50"
                onClick={() => setItems((current) => current.filter((currentItem) => currentItem.id !== item.id))}
                type="button"
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <Notice tone="info">{payload.note ?? 'Следующий квиз стартует после завершения текущего запуска.'}</Notice>
    </Modal>
  );
}
