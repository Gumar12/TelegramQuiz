import { Gauge, LockKeyhole, Phone, Power, RefreshCw, Trash2, UserRound } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Badge } from '../../ui/Badge';
import { Button } from '../../ui/Button';
import { AccountStatusBadge, getAccountSessionLabel } from './AccountStatusBadge';
import type { PublicAccountProfile } from './types';

type AccountProfileCardProps = {
  account: PublicAccountProfile;
  connectionActionsEnabled?: boolean;
  managementEnabled?: boolean;
  onConnectAccount?: (account: PublicAccountProfile) => void;
  onDeleteAccount?: (account: PublicAccountProfile) => Promise<void> | void;
  onDisableAccount?: (account: PublicAccountProfile) => void;
  onEnableAccount?: (account: PublicAccountProfile) => void;
  onReconnectAccount?: (account: PublicAccountProfile) => void;
  onSetActiveAccount?: (account: PublicAccountProfile) => void;
  switchEnabled?: boolean;
};

function isConnected(account: PublicAccountProfile) {
  return account.status === 'connected' && account.enabled !== false;
}

export function AccountProfileCard({
  account,
  connectionActionsEnabled = false,
  managementEnabled = false,
  onConnectAccount,
  onDeleteAccount,
  onDisableAccount,
  onEnableAccount,
  onReconnectAccount,
  onSetActiveAccount,
  switchEnabled = false,
}: AccountProfileCardProps) {
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const connected = isConnected(account);
  const canSwitch = switchEnabled && connected && !account.active && Boolean(onSetActiveAccount);
  const canDelete = managementEnabled && account.id !== 'default' && Boolean(onDeleteAccount);
  const canConnect = connectionActionsEnabled && account.status !== 'connected' && account.status !== 'disabled' && Boolean(onConnectAccount);
  const canReconnect = connectionActionsEnabled && account.status !== 'disabled' && Boolean(onReconnectAccount);
  const canDisable = managementEnabled && account.enabled !== false && Boolean(onDisableAccount);
  const canEnable = managementEnabled && account.enabled === false && Boolean(onEnableAccount);

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={[
              'flex size-11 shrink-0 items-center justify-center rounded-full',
              connected ? 'bg-[#FCE7F0] text-[#E85D8F]' : 'bg-gray-100 text-gray-500',
            ].join(' ')}
          >
            <UserRound className="size-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-xl font-bold tracking-normal text-gray-950">{account.name}</h3>
              <AccountStatusBadge status={account.status} />
              {account.active && <Badge tone="pink">активный</Badge>}
            </div>
            {deleteError && <p className="mt-2 text-sm font-semibold text-red-600">{deleteError}</p>}
            {account.disabledReason && <p className="mt-2 text-sm leading-6 text-amber-700">{account.disabledReason}</p>}
          </div>
        </div>
      </div>

      <dl className="mt-4 grid gap-3 text-sm text-gray-700 sm:grid-cols-3">
        <ProfileMetaRow icon={<Phone className="size-4" aria-hidden="true" />} label="Телефон" value={account.maskedPhone ?? 'не указан'} />
        <ProfileMetaRow
          icon={<LockKeyhole className="size-4" aria-hidden="true" />}
          label="Сессия"
          value={getAccountSessionLabel(account.sessionState)}
        />
        <ProfileMetaRow
          icon={<Gauge className="size-4" aria-hidden="true" />}
          label="Скорость по умолчанию"
          value={account.defaultSpeed ?? 'adaptive'}
        />
        {account.lastUsedAt && <ProfileMetaRow label="Последний запуск" value={account.lastUsedAt} />}
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        {canSwitch && (
          <Button
            onClick={() => onSetActiveAccount?.(account)}
            size="sm"
            variant="outline"
          >
            Сделать активным
          </Button>
        )}
        {account.status === 'connected' ? (
          canReconnect && (
            <Button
              icon={<RefreshCw className="size-4" aria-hidden="true" />}
              onClick={() => onReconnectAccount?.(account)}
              size="sm"
              variant="outline"
            >
              Переподключить
            </Button>
          )
        ) : (
          canConnect && (
            <Button
              icon={<RefreshCw className="size-4" aria-hidden="true" />}
              onClick={() => onConnectAccount?.(account)}
              size="sm"
              variant="outline"
            >
              Подключить
            </Button>
          )
        )}
        {account.enabled === false ? (
          canEnable && (
            <Button
              icon={<Power className="size-4" aria-hidden="true" />}
              onClick={() => onEnableAccount?.(account)}
              size="sm"
              variant="outline"
            >
              Включить
            </Button>
          )
        ) : (
          canDisable && (
            <Button
              icon={<Power className="size-4" aria-hidden="true" />}
              onClick={() => onDisableAccount?.(account)}
              size="sm"
              variant="danger"
            >
              Отключить
            </Button>
          )
        )}
        {canDelete && !deleteConfirm && (
          <Button
            icon={<Trash2 className="size-4" aria-hidden="true" />}
            onClick={() => {
              setDeleteError('');
              setDeleteConfirm(true);
            }}
            size="sm"
            variant="danger"
          >
            Удалить
          </Button>
        )}
        {canDelete && deleteConfirm && (
          <>
            <Button
              icon={<Trash2 className="size-4" aria-hidden="true" />}
              loading={deleting}
              onClick={async () => {
                setDeleting(true);
                setDeleteError('');
                try {
                  await onDeleteAccount?.(account);
                } catch (error) {
                  setDeleteError(error instanceof Error ? error.message : 'Не удалось удалить профиль.');
                  setDeleting(false);
                }
              }}
              size="sm"
              variant="danger"
            >
              Подтвердить удаление
            </Button>
            <Button
              disabled={deleting}
              onClick={() => {
                setDeleteConfirm(false);
                setDeleteError('');
              }}
              size="sm"
              variant="ghost"
            >
              Отмена
            </Button>
          </>
        )}
      </div>
    </article>
  );
}

function ProfileMetaRow({
  icon,
  label,
  value,
}: {
  icon?: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 rounded-md bg-gray-50 px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
      {icon && <span className="text-gray-500">{icon}</span>}
      <dt className="text-xs font-medium text-gray-500">{label}</dt>
      </div>
      <dd className="mt-1 truncate font-semibold text-gray-900">{value}</dd>
    </div>
  );
}
