import { OctagonAlert } from 'lucide-react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { Progress } from '../ui/Progress';
import type { StopRunModalPayload } from '../../state/modalStore';
import { IconCircle, MetaRow, Notice, SummaryCard } from './ModalBlocks';

type StopRunModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: StopRunModalPayload;
  onConfirm?: (runId: string) => void;
  isStopping?: boolean;
  error?: string;
};

export function StopRunModal({ isOpen, onClose, onConfirm, payload, isStopping = false, error }: StopRunModalProps) {
  const progress =
    payload.totalQuestions > 0 ? Math.round((payload.completedQuestions / payload.totalQuestions) * 100) : 0;
  const canStop = payload.canStop === true && Boolean(onConfirm);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Остановить запуск?"
      footer={
        <>
          <Button disabled={isStopping} onClick={onClose} variant="outline">
            Отмена
          </Button>
          <Button
            disabled={!canStop || isStopping}
            loading={isStopping}
            onClick={() => onConfirm?.(payload.runId)}
            variant="danger"
          >
            {isStopping ? 'Останавливаю…' : 'Остановить'}
          </Button>
        </>
      }
    >
      <IconCircle tone="danger">
        <OctagonAlert className="size-5" aria-hidden="true" />
      </IconCircle>
      <p className="mb-4 text-sm leading-6 text-gray-600">
        Квиз остановится после текущего безопасного шага. Продолжить можно будет из раздела запусков, если состояние
        сохранено.
      </p>

      <SummaryCard className="mb-4">
        <MetaRow label="Квиз" value={payload.quizTitle} />
        <MetaRow label="Прогресс" value={`${payload.completedQuestions} из ${payload.totalQuestions} вопросов`} />
        <MetaRow label="Аккаунт" value={payload.accountName} />
        <Progress value={progress} label="Текущий прогресс" />
      </SummaryCard>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
          {error}
        </div>
      )}

      <Notice tone="warning">Остановка не удалит квиз и не очистит очередь.</Notice>
    </Modal>
  );
}
