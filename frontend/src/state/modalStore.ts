import { useSyncExternalStore } from 'react';

export const MODAL_IDS = [
  'switch-account',
  'stop-run',
  'edit-queue',
  'launch-settings',
  'archive-delete-quiz',
  'unsaved-changes',
  'telegram-error',
] as const;

export type ModalId = (typeof MODAL_IDS)[number];

export type AccountConnectionStatus = 'connected' | 'disconnected' | 'needs_reconnect' | 'disabled';

export type AccountOption = {
  id: string;
  name: string;
  status: AccountConnectionStatus;
  active?: boolean;
  maskedPhone?: string;
  disabledReason?: string;
};

export type SwitchAccountModalPayload = {
  accounts: AccountOption[];
  activeAccountId?: string;
  manageAccountsDisabled?: boolean;
};

export type StopRunModalPayload = {
  runId: string;
  quizTitle: string;
  accountName: string;
  completedQuestions: number;
  totalQuestions: number;
  canStop?: boolean;
};

export type QueueItemStatus = 'ready' | 'needs_review' | 'blocked' | 'running';

export type QueueItem = {
  id: string;
  title: string;
  status: QueueItemStatus;
  questionCount?: number;
  disabledReason?: string;
};

export type EditQueueModalPayload = {
  items: QueueItem[];
  canAddQuiz?: boolean;
  canSaveOrder?: boolean;
  note?: string;
};

export type LaunchSpeed = 'normal' | 'fast';
export type LaunchRangeMode = 'all' | 'start_from';

export type LaunchSettingsValue = {
  accountId: string;
  speed: LaunchSpeed;
  shuffleOptions: boolean;
  telegramTitle: string;
  rangeMode: LaunchRangeMode;
  startFrom: number;
};

export type LaunchSettingsSelection = LaunchSettingsValue & {
  quizId: string;
};

export type LaunchSettingsModalPayload = {
  quizId: string;
  quizTitle: string;
  questionCount: number;
  errorCount: number;
  accounts: AccountOption[];
  defaults?: Partial<LaunchSettingsValue>;
  canQueue?: boolean;
  canStartNow?: boolean;
  validationFresh?: boolean;
};

export type ArchiveDeleteAction = 'archive' | 'delete';

export type ArchiveDeleteQuizModalPayload = {
  quizId: string;
  quizTitle: string;
  questionCount: number;
  defaultAction?: ArchiveDeleteAction;
  allowArchive?: boolean;
  allowHardDelete?: boolean;
};

export type UnsavedChangesModalPayload = {
  quizTitle: string;
  lastAutosaveLabel?: string;
  changedQuestionsCount?: number;
  canSave?: boolean;
};

export type TelegramErrorKind = 'session_expired' | 'flood_wait' | 'timeout' | 'rate_limited' | 'unknown';

export type TelegramErrorModalPayload = {
  accountName: string;
  quizTitle?: string;
  errorLabel: string;
  recommendation: string;
  kind?: TelegramErrorKind;
  canReconnect?: boolean;
  canOpenAccounts?: boolean;
  canRetryLater?: boolean;
};

export type ModalPayloadMap = {
  'switch-account': SwitchAccountModalPayload;
  'stop-run': StopRunModalPayload;
  'edit-queue': EditQueueModalPayload;
  'launch-settings': LaunchSettingsModalPayload;
  'archive-delete-quiz': ArchiveDeleteQuizModalPayload;
  'unsaved-changes': UnsavedChangesModalPayload;
  'telegram-error': TelegramErrorModalPayload;
};

export type ModalStoreSnapshot =
  | { modalId: null; payload: null }
  | {
      [Id in ModalId]: {
        modalId: Id;
        payload: ModalPayloadMap[Id];
      };
    }[ModalId];

type ModalStoreListener = () => void;

let snapshot: ModalStoreSnapshot = { modalId: null, payload: null };
const listeners = new Set<ModalStoreListener>();

function emitModalStoreChange() {
  listeners.forEach((listener) => listener());
}

export function openModal<Id extends ModalId>(modalId: Id, payload: ModalPayloadMap[Id]) {
  snapshot = { modalId, payload } as ModalStoreSnapshot;
  emitModalStoreChange();
}

export function closeModal() {
  snapshot = { modalId: null, payload: null };
  emitModalStoreChange();
}

export function getModalSnapshot() {
  return snapshot;
}

export function subscribeModalStore(listener: ModalStoreListener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useModalStore() {
  return useSyncExternalStore(subscribeModalStore, getModalSnapshot, getModalSnapshot);
}
