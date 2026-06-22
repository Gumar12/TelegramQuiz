export type AccountConnectionStatus = 'connected' | 'disconnected' | 'needs_reconnect' | 'disabled';
export type AccountSessionState = 'authorized' | 'needs_auth' | 'missing' | 'expired' | 'unknown';
export type AccountDefaultSpeed = 'normal' | 'fast' | 'adaptive';

export type PublicAccountProfile = {
  active?: boolean;
  defaultSpeed?: AccountDefaultSpeed;
  disabledReason?: string;
  enabled?: boolean;
  id: string;
  lastUsedAt?: string;
  maskedPhone?: string;
  name: string;
  sessionState?: AccountSessionState;
  status: AccountConnectionStatus;
};
