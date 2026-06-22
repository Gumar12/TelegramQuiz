import { useEffect, useState } from 'react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { Badge } from '../ui/Badge';
import type { AccountOption, SwitchAccountModalPayload } from '../../state/modalStore';
import { AccountStatusBadge, ModalSubtitle } from './ModalBlocks';

type SwitchAccountModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: SwitchAccountModalPayload;
  onConfirm?: (accountId: string) => void;
  onManageAccounts?: () => void;
};

function canUseAccount(account: AccountOption) {
  return account.status === 'connected' && !account.disabledReason;
}

function getInitialAccountId(payload: SwitchAccountModalPayload) {
  return (
    payload.activeAccountId ??
    payload.accounts.find((account) => account.active)?.id ??
    payload.accounts.find(canUseAccount)?.id ??
    ''
  );
}

export function SwitchAccountModal({
  isOpen,
  onClose,
  onConfirm,
  onManageAccounts,
  payload,
}: SwitchAccountModalProps) {
  const activeAccountId = payload.activeAccountId ?? payload.accounts.find((account) => account.active)?.id;
  const [selectedAccountId, setSelectedAccountId] = useState(getInitialAccountId(payload));

  useEffect(() => {
    setSelectedAccountId(getInitialAccountId(payload));
  }, [payload]);

  const selectedAccount = payload.accounts.find((account) => account.id === selectedAccountId);
  const canConfirm = Boolean(
    selectedAccount &&
      canUseAccount(selectedAccount) &&
      selectedAccount.id !== activeAccountId &&
      onConfirm,
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Сменить аккаунт"
      footer={
        <>
          <Button
            className="mr-auto"
            disabled={payload.manageAccountsDisabled || !onManageAccounts}
            onClick={onManageAccounts}
            variant="ghost"
          >
            Управлять аккаунтами
          </Button>
          <Button onClick={onClose} variant="outline">
            Отмена
          </Button>
          <Button disabled={!canConfirm} onClick={() => selectedAccountId && onConfirm?.(selectedAccountId)} variant="primary">
            Сделать активным
          </Button>
        </>
      }
    >
      <ModalSubtitle>Новые запуски будут использовать выбранный аккаунт.</ModalSubtitle>

      <div className="space-y-3">
        {payload.accounts.map((account) => {
          const selectable = canUseAccount(account);
          const selected = selectedAccountId === account.id;

          return (
            <button
              className={[
                'flex w-full items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition-colors',
                selected ? 'border-[#E85D8F] bg-[#FCE7F0]' : 'border-gray-200 bg-white hover:bg-gray-50',
                selectable ? '' : 'cursor-not-allowed opacity-60',
              ].join(' ')}
              disabled={!selectable}
              key={account.id}
              onClick={() => setSelectedAccountId(account.id)}
              type="button"
            >
              <span className="min-w-0 space-y-2">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-gray-950">{account.name}</span>
                  {account.active && <Badge tone="pink">активный</Badge>}
                  <AccountStatusBadge status={account.status} />
                </span>
                <span className="block text-sm text-gray-500">
                  {account.maskedPhone ? `Телефон: ${account.maskedPhone}` : account.disabledReason ?? 'Требуется подключение'}
                </span>
              </span>
              <span
                aria-hidden="true"
                className={[
                  'flex size-5 shrink-0 items-center justify-center rounded-full border',
                  selected ? 'border-[#E85D8F] bg-[#E85D8F]' : 'border-gray-300 bg-white',
                ].join(' ')}
              >
                {selected && <span className="size-2 rounded-full bg-white" />}
              </span>
            </button>
          );
        })}
      </div>
    </Modal>
  );
}
