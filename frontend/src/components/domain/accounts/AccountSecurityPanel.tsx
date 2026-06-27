import { useEffect, useState } from 'react';
import { Plus, ShieldCheck } from 'lucide-react';
import { api } from '../../../api';
import type { DeepSeekKeyStatus } from '../../../types';
import { Button } from '../../ui/Button';
import { Panel, PanelBody, PanelHeader } from '../../ui/Panel';

type AccountSecurityPanelProps = {
  connectionActionsEnabled?: boolean;
  onAddTelegram?: () => void;
  onAccountCreated?: () => void;
};

export function AccountSecurityPanel({ connectionActionsEnabled = false, onAccountCreated }: AccountSecurityPanelProps) {
  return (
    <div className="space-y-5">
      {connectionActionsEnabled && <AddAccountForm onCreated={onAccountCreated} />}

      <Panel>
        <PanelHeader title="Безопасность" />
        <PanelBody className="space-y-4 pt-4">
          <div className="flex size-16 items-center justify-center rounded-full bg-[#FCE7F0] text-[#E85D8F]">
            <ShieldCheck className="size-8" aria-hidden="true" />
          </div>
          <div className="space-y-2">
            <p className="text-base font-bold text-gray-950">Секреты не показываются в интерфейсе.</p>
            <p className="text-sm leading-6 text-gray-600">
              Секретные данные и session-файлы остаются на backend-стороне.
            </p>
          </div>
        </PanelBody>
      </Panel>

      <DeepSeekKeyPanel />
    </div>
  );
}

const ADD_ACCOUNT_INPUT_CLASS =
  'mt-2 min-h-11 w-full rounded-md border border-gray-200 px-3 text-base text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]';

function AddAccountForm({ onCreated }: { onCreated?: () => void }) {
  const [displayName, setDisplayName] = useState('');
  const [apiId, setApiId] = useState('');
  const [apiHash, setApiHash] = useState('');
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const canSubmit =
    Boolean(displayName.trim() && apiId.trim() && apiHash.trim() && phone.trim()) && !busy;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const apiIdNumber = Number(apiId.trim());
    if (!Number.isInteger(apiIdNumber) || apiIdNumber <= 0) {
      setError('api_id должен быть числом (только цифры).');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api.createAccount({
        displayName: displayName.trim(),
        apiId: apiIdNumber,
        apiHash: apiHash.trim(),
        phone: phone.trim(),
      });
      setDisplayName('');
      setApiId('');
      setApiHash('');
      setPhone('');
      onCreated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось создать профиль.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <PanelHeader title="Подключить аккаунт" />
      <PanelBody className="space-y-4 pt-4">
        <p className="text-sm leading-6 text-gray-600">
          Создайте Telegram-профиль. <span className="font-semibold">api_id</span> и{' '}
          <span className="font-semibold">api_hash</span> получите на my.telegram.org → API development tools.
        </p>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit();
          }}
        >
          <label className="block text-sm font-semibold text-gray-700">
            Название профиля
            <input
              autoComplete="off"
              className={ADD_ACCOUNT_INPUT_CLASS}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Например: Рабочий"
              value={displayName}
            />
          </label>
          <label className="block text-sm font-semibold text-gray-700">
            api_id
            <input
              autoComplete="off"
              className={ADD_ACCOUNT_INPUT_CLASS}
              inputMode="numeric"
              onChange={(event) => setApiId(event.target.value)}
              placeholder="12345678"
              value={apiId}
            />
          </label>
          <label className="block text-sm font-semibold text-gray-700">
            api_hash
            <input
              autoComplete="off"
              className={ADD_ACCOUNT_INPUT_CLASS}
              onChange={(event) => setApiHash(event.target.value)}
              placeholder="abcdef0123456789abcdef0123456789"
              value={apiHash}
            />
          </label>
          <label className="block text-sm font-semibold text-gray-700">
            Телефон
            <input
              autoComplete="off"
              className={ADD_ACCOUNT_INPUT_CLASS}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+71234567890"
              value={phone}
            />
          </label>
          <Button
            className="w-full"
            disabled={!canSubmit}
            icon={<Plus className="size-5" aria-hidden="true" />}
            loading={busy}
            type="submit"
            variant="primary"
          >
            Создать профиль
          </Button>
        </form>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
            {error}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}

function DeepSeekKeyPanel() {
  const [status, setStatus] = useState<DeepSeekKeyStatus | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getDeepSeekKeyStatus()
      .then((next) => {
        if (!cancelled) setStatus(next);
      })
      .catch(() => {
        if (!cancelled) setStatus({ configured: false, masked: '', source: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    const trimmed = apiKey.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const next = await api.saveDeepSeekKey(trimmed);
      setStatus(next);
      setApiKey('');
      setFeedback({ kind: 'success', text: 'Ключ сохранён.' });
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : 'Не удалось сохранить ключ.' });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const next = await api.deleteDeepSeekKey();
      setStatus(next);
      setFeedback({ kind: 'success', text: 'Ключ удалён.' });
    } catch (error) {
      setFeedback({ kind: 'error', text: error instanceof Error ? error.message : 'Не удалось удалить ключ.' });
    } finally {
      setBusy(false);
    }
  };

  const configured = status?.configured ?? false;
  const canDelete = status?.source === 'runtime';

  return (
    <Panel>
      <PanelHeader title="DeepSeek API" />
      <PanelBody className="space-y-4 pt-4">
        <p className="text-sm leading-6 text-gray-600">
          Ключ используется для AI-разметки DOCX. Хранится на backend, в интерфейсе не показывается.
        </p>

        <div className="rounded-md border border-gray-200 bg-gray-50 px-4 py-3 text-sm">
          {configured ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                ключ задан
              </span>
              {status?.masked && <span className="font-mono text-gray-700">{status.masked}</span>}
              {status?.source === 'env' && <span className="text-xs text-gray-500">(из .env)</span>}
            </div>
          ) : (
            <span className="font-semibold text-gray-500">Ключ не задан</span>
          )}
        </div>

        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSave();
          }}
        >
          <label className="block text-sm font-semibold text-gray-700" htmlFor="deepseek-api-key">
            {configured ? 'Новый ключ' : 'API-ключ'}
            <input
              autoComplete="off"
              className="mt-2 min-h-11 w-full rounded-md border border-gray-200 px-3 text-base text-gray-950 focus:border-[#E85D8F] focus:outline-none focus:ring-2 focus:ring-[#FCE7F0]"
              id="deepseek-api-key"
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk-..."
              type="password"
              value={apiKey}
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <Button disabled={!apiKey.trim()} loading={busy} type="submit" variant="primary">
              {configured ? 'Обновить ключ' : 'Сохранить ключ'}
            </Button>
            {canDelete && (
              <Button disabled={busy} onClick={() => void handleDelete()} type="button" variant="outline">
                Удалить ключ
              </Button>
            )}
          </div>
        </form>

        {feedback && (
          <div
            className={
              feedback.kind === 'success'
                ? 'rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700'
                : 'rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700'
            }
          >
            {feedback.text}
          </div>
        )}
      </PanelBody>
    </Panel>
  );
}
