import { useEffect, useState } from 'react';
import {
  AccountProfileCard,
  AccountSecurityPanel,
  type PublicAccountProfile,
} from '../components/domain/accounts';
import { Button } from '../components/ui/Button';
import { Modal } from '../components/ui/Modal';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';

export type TelegramLoginPanelState = {
  accountName: string;
  error?: string;
  loginId?: string;
  loading?: boolean;
  phoneMasked?: string;
  profileId?: string;
  step: 'starting' | 'code_sent' | 'password_required';
};

export type AccountsScreenProps = {
  accounts?: PublicAccountProfile[];
  connectionActionsEnabled?: boolean;
  telegramLogin?: TelegramLoginPanelState | null;
  managementEnabled?: boolean;
  onAddTelegram?: () => void;
  onCancelTelegramLogin?: () => void;
  onConnectAccount?: (account: PublicAccountProfile) => void;
  onDeleteAccount?: (account: PublicAccountProfile) => Promise<void> | void;
  onDisableAccount?: (account: PublicAccountProfile) => void;
  onEnableAccount?: (account: PublicAccountProfile) => void;
  onReconnectAccount?: (account: PublicAccountProfile) => void;
  onRestartTelegramLogin?: () => void;
  onSetActiveAccount?: (account: PublicAccountProfile) => void;
  onSubmitTelegramCode?: (code: string) => void;
  onSubmitTelegramPassword?: (password: string) => void;
  switchEnabled?: boolean;
};

export default function AccountsScreen({
  accounts = [],
  connectionActionsEnabled = false,
  telegramLogin = null,
  managementEnabled = false,
  onAddTelegram,
  onCancelTelegramLogin,
  onConnectAccount,
  onDeleteAccount,
  onDisableAccount,
  onEnableAccount,
  onReconnectAccount,
  onRestartTelegramLogin,
  onSetActiveAccount,
  onSubmitTelegramCode,
  onSubmitTelegramPassword,
  switchEnabled = false,
}: AccountsScreenProps) {
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Аккаунты Telegram</h1>
        <p className="text-sm leading-6 text-gray-600">
          Выберите аккаунт, через который будут запускаться новые квизы.
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel>
          <PanelHeader title="Подключенные аккаунты" />
          <PanelBody className="space-y-4 pt-4">
            {accounts.length > 0 ? (
              accounts.map((account) => (
                <div key={account.id}>
                  <AccountProfileCard
                    account={account}
                    connectionActionsEnabled={connectionActionsEnabled}
                    managementEnabled={managementEnabled}
                    onConnectAccount={onConnectAccount}
                    onDeleteAccount={onDeleteAccount}
                    onDisableAccount={onDisableAccount}
                    onEnableAccount={onEnableAccount}
                    onReconnectAccount={onReconnectAccount}
                    onSetActiveAccount={onSetActiveAccount}
                    switchEnabled={switchEnabled}
                  />
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-5 py-10 text-center">
                <p className="text-base font-semibold text-gray-950">Профили не подключены</p>
                <p className="mt-2 text-sm leading-6 text-gray-500">
                  Нет доступных профилей для новых запусков.
                </p>
              </div>
            )}
          </PanelBody>
        </Panel>

        <div className="space-y-5 xl:sticky xl:top-5 xl:self-start">
          <AccountSecurityPanel connectionActionsEnabled={connectionActionsEnabled} onAddTelegram={onAddTelegram} />
        </div>
      </div>

      {telegramLogin && (
        <TelegramLoginModal
          login={telegramLogin}
          onCancel={onCancelTelegramLogin}
          onRestart={onRestartTelegramLogin}
          onSubmitCode={onSubmitTelegramCode}
          onSubmitPassword={onSubmitTelegramPassword}
        />
      )}
    </div>
  );
}

export type { PublicAccountProfile };

function TelegramLoginModal({
  login,
  onCancel,
  onRestart,
  onSubmitCode,
  onSubmitPassword,
}: {
  login: TelegramLoginPanelState;
  onCancel?: () => void;
  onRestart?: () => void;
  onSubmitCode?: (code: string) => void;
  onSubmitPassword?: (password: string) => void;
}) {
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    setCode('');
    setPassword('');
  }, [login.accountName, login.error, login.loginId, login.phoneMasked, login.step]);

  const isCodeStep = login.step === 'code_sent';
  const isPasswordStep = login.step === 'password_required';
  const normalizedError = login.error?.toLowerCase().replace('ё', 'е') ?? '';
  const isExpiredCodeError =
    normalizedError.includes('expired')
    || normalizedError.includes('истек')
    || normalizedError.includes('устарел');

  const canRequestCodeAgain = Boolean(onRestart) && (isCodeStep || Boolean(login.error));

  return (
    <Modal isOpen onClose={() => onCancel?.()} title="Вход в Telegram">
      <div className="space-y-4">
        <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-3">
          <div className="text-sm text-gray-500">Аккаунт</div>
          <div className="mt-1 text-base font-semibold text-gray-950">{login.accountName}</div>
          {login.phoneMasked && (
            <div className="mt-2 text-sm text-gray-600">Код отправлен на {login.phoneMasked}</div>
          )}
        </div>

        {login.step === 'starting' && (
          <p className="text-sm leading-6 text-gray-600">Отправляем код подтверждения.</p>
        )}

        {isCodeStep && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (code.trim() && !isExpiredCodeError) onSubmitCode?.(code.trim());
            }}
          >
            <label className="block text-sm font-semibold text-gray-700" htmlFor="telegram-login-code">
              Код из Telegram
              <input
                autoComplete="one-time-code"
                autoFocus
                className="mt-2 min-h-11 w-full rounded-md border border-gray-200 px-3 text-base text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]"
                disabled={isExpiredCodeError || login.loading}
                id="telegram-login-code"
                inputMode="numeric"
                onChange={(event) => setCode(event.target.value)}
                value={code}
              />
            </label>
            <Button disabled={!code.trim() || isExpiredCodeError} loading={login.loading} type="submit" variant="primary">
              Подтвердить код
            </Button>
          </form>
        )}

        {isPasswordStep && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (password) onSubmitPassword?.(password);
            }}
          >
            <label className="block text-sm font-semibold text-gray-700" htmlFor="telegram-login-password">
              Пароль 2FA
              <input
                autoComplete="current-password"
                autoFocus
                className="mt-2 min-h-11 w-full rounded-md border border-gray-200 px-3 text-base text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]"
                id="telegram-login-password"
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                value={password}
              />
            </label>
            <Button disabled={!password} loading={login.loading} type="submit" variant="primary">
              Подтвердить вход
            </Button>
          </form>
        )}

        {login.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {login.error}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-3 border-t border-gray-200 pt-4">
          <Button disabled={login.loading} onClick={onCancel} variant="ghost">
            Отмена
          </Button>
          {canRequestCodeAgain && (
            <Button disabled={login.loading || !onRestart} onClick={onRestart} variant="outline">
              {isExpiredCodeError ? 'Запросить новый код' : 'Код не пришёл, запросить снова'}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
