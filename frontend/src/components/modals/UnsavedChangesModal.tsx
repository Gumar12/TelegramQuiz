import { Save } from 'lucide-react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import type { UnsavedChangesModalPayload } from '../../state/modalStore';
import { IconCircle, MetaRow, SummaryCard } from './ModalBlocks';

type UnsavedChangesModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: UnsavedChangesModalPayload;
  onDiscard?: () => void;
  onSaveAndExit?: () => void;
  onStay?: () => void;
};

export function UnsavedChangesModal({
  isOpen,
  onClose,
  onDiscard,
  onSaveAndExit,
  onStay,
  payload,
}: UnsavedChangesModalProps) {
  const canSave = payload.canSave !== false && Boolean(onSaveAndExit);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Есть несохранённые изменения"
      footer={
        <>
          <Button disabled={!onDiscard} onClick={onDiscard} variant="danger">
            Выйти без сохранения
          </Button>
          <Button
            onClick={() => {
              onStay?.();
              onClose();
            }}
            variant="outline"
          >
            Остаться
          </Button>
          <Button disabled={!canSave} onClick={onSaveAndExit} variant="primary">
            Сохранить и выйти
          </Button>
        </>
      }
    >
      <IconCircle tone="warning">
        <Save className="size-5" aria-hidden="true" />
      </IconCircle>
      <p className="mb-4 text-sm leading-6 text-gray-600">
        Вы изменили вопросы в квизе {payload.quizTitle}. Сохраните изменения перед выходом или вернитесь в редактор.
      </p>

      <SummaryCard>
        <MetaRow label="Последний автосейв" value={payload.lastAutosaveLabel ?? 'нет данных'} />
        <MetaRow label="Изменено" value={`${payload.changedQuestionsCount ?? 0} вопроса`} />
      </SummaryCard>
    </Modal>
  );
}
