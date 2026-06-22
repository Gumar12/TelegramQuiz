import { Badge } from '../../ui/Badge';
import type { RunQueueStatus, RunStatus } from './types';

type BadgeTone = 'neutral' | 'pink' | 'success' | 'warning' | 'danger' | 'info' | 'violet';

const runStatusMeta: Record<RunStatus, { label: string; tone: BadgeTone }> = {
  blocked: { label: 'Блокирован', tone: 'danger' },
  cancelled: { label: 'Остановлен', tone: 'danger' },
  completed: { label: 'Завершен', tone: 'success' },
  cooldown: { label: 'Ожидание', tone: 'warning' },
  failed: { label: 'Ошибка', tone: 'danger' },
  paused: { label: 'Пауза', tone: 'warning' },
  queued: { label: 'В очереди', tone: 'info' },
  running: { label: 'Выполняется', tone: 'success' },
};

const queueStatusMeta: Record<RunQueueStatus, { label: string; tone: BadgeTone }> = {
  blocked: { label: 'заблокирован', tone: 'danger' },
  needs_review: { label: 'нужно исправить', tone: 'danger' },
  ready: { label: 'готов', tone: 'success' },
  running: { label: 'в запуске', tone: 'info' },
};

export function getRunStatusLabel(status: RunStatus) {
  return runStatusMeta[status].label;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const meta = runStatusMeta[status];

  return (
    <Badge className="gap-1.5" tone={meta.tone}>
      <span className="size-2 rounded-full bg-current" aria-hidden="true" />
      {meta.label}
    </Badge>
  );
}

export function RunQueueStatusBadge({ status }: { status: RunQueueStatus }) {
  const meta = queueStatusMeta[status];

  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}
