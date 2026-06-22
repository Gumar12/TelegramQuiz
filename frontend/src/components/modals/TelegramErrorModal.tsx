import { Unplug } from 'lucide-react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import type { TelegramErrorModalPayload } from '../../state/modalStore';
import { IconCircle, MetaRow, Notice, SummaryCard } from './ModalBlocks';

type TelegramErrorModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: TelegramErrorModalPayload;
  onOpenAccounts?: () => void;
  onReconnect?: () => void;
  onRetryLater?: () => void;
};

export function TelegramErrorModal({
  isOpen,
  onClose,
  onOpenAccounts,
  onReconnect,
  onRetryLater,
  payload,
}: TelegramErrorModalProps) {
  const canRetryLater = payload.canRetryLater !== false && Boolean(onRetryLater);
  const canOpenAccounts = payload.canOpenAccounts !== false && Boolean(onOpenAccounts);
  const canReconnect = payload.canReconnect === true && Boolean(onReconnect);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Telegram требует внимания"
      footer={
        <>
          <Button disabled={!canRetryLater} onClick={onRetryLater} variant="outline">
            Повторить позже
          </Button>
          <Button disabled={!canOpenAccounts} onClick={onOpenAccounts} variant="outline">
            Открыть аккаунты
          </Button>
          <Button disabled={!canReconnect} onClick={onReconnect} variant="primary">
            Переподключить
          </Button>
        </>
      }
    >
      <IconCircle tone="danger">
        <Unplug className="size-5" aria-hidden="true" />
      </IconCircle>
      <p className="mb-4 text-sm font-semibold text-gray-600">Запуск временно приостановлен.</p>

      <SummaryCard className="mb-4">
        <MetaRow label="Аккаунт" value={payload.accountName} />
        {payload.quizTitle && <MetaRow label="Квиз" value={payload.quizTitle} />}
        <MetaRow label="Ошибка" value={payload.errorLabel} />
        <MetaRow label="Рекомендация" value={payload.recommendation} />
      </SummaryCard>

      <Notice tone="warning">Если это ограничение Telegram, повторите позже.</Notice>
    </Modal>
  );
}
