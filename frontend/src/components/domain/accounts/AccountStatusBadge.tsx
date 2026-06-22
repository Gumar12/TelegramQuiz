import { Badge } from '../../ui/Badge';
import type { AccountConnectionStatus, AccountSessionState } from './types';

type BadgeTone = 'neutral' | 'pink' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

const connectionMeta: Record<AccountConnectionStatus, { label: string; tone: BadgeTone }> = {
  connected: { label: 'подключен', tone: 'success' },
  disabled: { label: 'отключен', tone: 'neutral' },
  disconnected: { label: 'не подключен', tone: 'neutral' },
  needs_reconnect: { label: 'нужно переподключить', tone: 'warning' },
};

const sessionMeta: Record<AccountSessionState, string> = {
  authorized: 'авторизована',
  expired: 'истекла',
  missing: 'не найдена',
  needs_auth: 'требуется подключение',
  unknown: 'неизвестно',
};

export function getAccountStatusLabel(status: AccountConnectionStatus) {
  return connectionMeta[status].label;
}

export function getAccountSessionLabel(sessionState: AccountSessionState = 'unknown') {
  return sessionMeta[sessionState];
}

export function AccountStatusBadge({ status }: { status: AccountConnectionStatus }) {
  const meta = connectionMeta[status];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
