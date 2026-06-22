import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import type { ArchiveDeleteAction, ArchiveDeleteQuizModalPayload } from '../../state/modalStore';
import { IconCircle, Notice } from './ModalBlocks';

type ArchiveDeleteQuizModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: ArchiveDeleteQuizModalPayload;
  error?: string;
  isSubmitting?: boolean;
  onConfirm?: (options: { quizId: string; action: ArchiveDeleteAction }) => void;
};

function getInitialAction(payload: ArchiveDeleteQuizModalPayload): ArchiveDeleteAction {
  if (payload.defaultAction === 'delete' && payload.allowHardDelete === true) return 'delete';
  return 'archive';
}

export function ArchiveDeleteQuizModal({
  error,
  isOpen,
  isSubmitting = false,
  onClose,
  onConfirm,
  payload,
}: ArchiveDeleteQuizModalProps) {
  const [action, setAction] = useState<ArchiveDeleteAction>(getInitialAction(payload));
  const archiveAllowed = payload.allowArchive !== false && !isSubmitting;
  const hardDeleteAllowed = payload.allowHardDelete === true && !isSubmitting;
  const canConfirm = Boolean(
    !isSubmitting
      && onConfirm
      && ((action === 'archive' && archiveAllowed) || (action === 'delete' && hardDeleteAllowed)),
  );

  useEffect(() => {
    setAction(getInitialAction(payload));
  }, [payload]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Что сделать с квизом?"
      footer={
        <>
          <Button onClick={onClose} variant="outline">
            Отмена
          </Button>
          <Button
            disabled={!canConfirm}
            loading={isSubmitting}
            onClick={() => onConfirm?.({ quizId: payload.quizId, action })}
            variant={action === 'delete' ? 'danger' : 'primary'}
          >
            Подтвердить
          </Button>
        </>
      }
    >
      <IconCircle tone="danger">
        <Trash2 className="size-5" aria-hidden="true" />
      </IconCircle>
      <p className="mb-4 text-sm font-semibold text-gray-700">
        {payload.quizTitle} · {payload.questionCount} вопросов
      </p>

      <div className="space-y-3">
        <button
          className={[
            'flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
            action === 'archive' ? 'border-[#E85D8F] bg-[#FCE7F0]' : 'border-gray-200 bg-white hover:bg-gray-50',
            archiveAllowed ? '' : 'cursor-not-allowed opacity-60',
          ].join(' ')}
          disabled={!archiveAllowed}
          onClick={() => setAction('archive')}
          type="button"
        >
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-[#E85D8F]">
            {action === 'archive' && <span className="size-2 rounded-full bg-[#E85D8F]" />}
          </span>
          <span>
            <span className="block font-semibold text-gray-950">Архивировать</span>
            <span className="mt-1 block text-sm leading-6 text-gray-500">
              Квиз исчезнет из активного списка, но его можно будет восстановить.
            </span>
          </span>
        </button>

        <button
          className={[
            'flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
            action === 'delete' ? 'border-red-300 bg-red-50' : 'border-gray-200 bg-white hover:bg-red-50',
            hardDeleteAllowed ? '' : 'cursor-not-allowed opacity-60',
          ].join(' ')}
          disabled={!hardDeleteAllowed}
          onClick={() => setAction('delete')}
          type="button"
        >
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-red-400">
            {action === 'delete' && <span className="size-2 rounded-full bg-red-500" />}
          </span>
          <span>
            <span className="block font-semibold text-red-700">Удалить навсегда</span>
            <span className="mt-1 block text-sm leading-6 text-gray-500">
              Файл квиза и история локальных изменений будут удалены.
            </span>
            {!hardDeleteAllowed && (
              <span className="mt-1 block text-xs font-semibold text-red-600">
                Недоступно до подключения безопасного подтверждения.
              </span>
            )}
          </span>
        </button>
      </div>

      <div className="mt-4">
        <Notice tone="danger">Удаление нельзя отменить.</Notice>
      </div>
      {error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          {error}
        </div>
      )}
    </Modal>
  );
}
