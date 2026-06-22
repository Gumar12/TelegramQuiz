import { useEffect, useMemo, useState } from 'react';
import { Rocket } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import type {
  AccountOption,
  LaunchRangeMode,
  LaunchSettingsModalPayload,
  LaunchSettingsSelection,
  LaunchSpeed,
} from '../../state/modalStore';
import { AccountStatusBadge, MetaRow, Notice, SummaryCard, ValidationStateIcon } from './ModalBlocks';

type LaunchSettingsModalProps = {
  isOpen: boolean;
  onClose: () => void;
  payload: LaunchSettingsModalPayload;
  onAddToQueue?: (settings: LaunchSettingsSelection) => void;
  onStartNow?: (settings: LaunchSettingsSelection) => void;
};

const speeds: LaunchSpeed[] = ['normal', 'fast'];

function firstConnectedAccount(accounts: AccountOption[]) {
  return accounts.find((account) => account.status === 'connected' && !account.disabledReason);
}

function buildInitialSettings(payload: LaunchSettingsModalPayload): LaunchSettingsSelection {
  return {
    quizId: payload.quizId,
    accountId: payload.defaults?.accountId ?? firstConnectedAccount(payload.accounts)?.id ?? '',
    speed: payload.defaults?.speed ?? 'normal',
    shuffleOptions: payload.defaults?.shuffleOptions ?? false,
    telegramTitle: payload.defaults?.telegramTitle ?? payload.quizTitle,
    rangeMode: payload.defaults?.rangeMode ?? 'all',
    startFrom: payload.defaults?.startFrom ?? 1,
  };
}

export function LaunchSettingsModal({
  isOpen,
  onAddToQueue,
  onClose,
  onStartNow,
  payload,
}: LaunchSettingsModalProps) {
  const [settings, setSettings] = useState(buildInitialSettings(payload));

  useEffect(() => {
    setSettings(buildInitialSettings(payload));
  }, [payload]);

  const selectedAccount = useMemo(
    () => payload.accounts.find((account) => account.id === settings.accountId),
    [payload.accounts, settings.accountId],
  );

  const accountReady = selectedAccount?.status === 'connected' && !selectedAccount.disabledReason;
  const canQueue = payload.canQueue === true && accountReady && Boolean(onAddToQueue);
  const canStartNow = payload.canStartNow === true && payload.validationFresh === true && accountReady && Boolean(onStartNow);

  const updateSettings = (patch: Partial<LaunchSettingsSelection>) => {
    setSettings((current) => ({ ...current, ...patch }));
  };

  const setRangeMode = (rangeMode: LaunchRangeMode) => {
    updateSettings({ rangeMode, startFrom: rangeMode === 'all' ? 1 : settings.startFrom });
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Настройка запуска"
      footer={
        <>
          <Button onClick={onClose} variant="outline">
            Отмена
          </Button>
          <Button disabled={!canQueue} onClick={() => onAddToQueue?.(settings)} variant="outline">
            Добавить в очередь
          </Button>
          <Button
            disabled={!canStartNow}
            icon={<Rocket className="size-4" aria-hidden="true" />}
            onClick={() => onStartNow?.(settings)}
            variant="primary"
          >
            Запустить сейчас
          </Button>
        </>
      }
    >
      <p className="mb-4 text-sm leading-6 text-gray-500">Проверьте параметры перед отправкой квиза в Telegram.</p>

      <SummaryCard className="mb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-base font-bold text-gray-950">{payload.quizTitle}</div>
            <div className="mt-1 text-sm text-gray-500">
              {payload.questionCount} вопросов · {payload.errorCount} ошибок ·{' '}
              {payload.errorCount === 0 ? 'готов к запуску' : 'нужна проверка'}
            </div>
          </div>
          <Badge tone={payload.errorCount === 0 ? 'success' : 'danger'}>
            {payload.errorCount === 0 ? 'готов' : 'нужна проверка'}
          </Badge>
        </div>
      </SummaryCard>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-normal text-gray-500">Аккаунт запуска</span>
          <select
            className="min-h-11 w-full rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]"
            onChange={(event) => updateSettings({ accountId: event.target.value })}
            value={settings.accountId}
          >
            {payload.accounts.map((account) => (
              <option disabled={account.status !== 'connected'} key={account.id} value={account.id}>
                {account.name} · {account.status === 'connected' ? 'подключён' : 'не подключён'}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-normal text-gray-500">Название в Telegram</span>
          <input
            className="min-h-11 w-full rounded-md border border-gray-200 px-3 text-sm font-semibold text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]"
            onChange={(event) => updateSettings({ telegramTitle: event.target.value })}
            type="text"
            value={settings.telegramTitle}
          />
        </label>

        <div className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-normal text-gray-500">Скорость</span>
          <div className="grid grid-cols-2 rounded-md border border-gray-200 bg-gray-50 p-1">
            {speeds.map((speed) => (
              <button
                className={[
                  'min-h-9 rounded px-2 text-sm font-semibold transition-colors',
                  settings.speed === speed ? 'bg-white text-[#E85D8F] shadow-sm' : 'text-gray-600 hover:text-gray-950',
                ].join(' ')}
                key={speed}
                onClick={() => updateSettings({ speed })}
                type="button"
              >
                {speed}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <span className="text-xs font-semibold uppercase tracking-normal text-gray-500">Диапазон</span>
          <div className="space-y-2 rounded-md border border-gray-200 p-3">
            <label className="flex items-center gap-2 text-sm font-semibold text-gray-800">
              <input
                checked={settings.rangeMode === 'all'}
                onChange={() => setRangeMode('all')}
                type="radio"
              />
              Весь квиз
            </label>
            <label className="flex items-center gap-2 text-sm font-semibold text-gray-800">
              <input
                checked={settings.rangeMode === 'start_from'}
                onChange={() => setRangeMode('start_from')}
                type="radio"
              />
              Начать с вопроса
            </label>
            <input
              className="min-h-10 w-full rounded-md border border-gray-200 px-3 text-sm disabled:bg-gray-50 disabled:text-gray-400"
              disabled={settings.rangeMode !== 'start_from'}
              min={1}
              onChange={(event) => updateSettings({ startFrom: Math.max(1, Number(event.target.value) || 1) })}
              type="number"
              value={settings.startFrom}
            />
          </div>
        </div>

        <label className="flex items-center justify-between gap-4 rounded-md border border-gray-200 px-3 py-3 sm:col-span-2">
          <span>
            <span className="block text-sm font-semibold text-gray-950">Перемешивать варианты</span>
            <span className="text-sm text-gray-500">Порядок ответов изменится перед отправкой.</span>
          </span>
          <input
            checked={settings.shuffleOptions}
            onChange={(event) => updateSettings({ shuffleOptions: event.target.checked })}
            type="checkbox"
          />
        </label>
      </div>

      <div className="mt-4 space-y-3">
        {selectedAccount && (
          <SummaryCard>
            <MetaRow label="Аккаунт запуска" value={selectedAccount.name} />
            <MetaRow label="Статус" value={<AccountStatusBadge status={selectedAccount.status} />} />
          </SummaryCard>
        )}
        <Notice tone={payload.validationFresh ? 'success' : 'warning'}>
          <span className="inline-flex items-center gap-2">
            <ValidationStateIcon ok={payload.validationFresh === true} />
            Upload начнётся только после свежей проверки JSON.
          </span>
        </Notice>
      </div>
    </Modal>
  );
}
