import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Panel, PanelBody } from '../ui/Panel';
import type {
  AccountConnectionStatus,
  QueueItemStatus,
} from '../../state/modalStore';

type Tone = 'info' | 'success' | 'warning' | 'danger' | 'neutral';

const noticeToneClass: Record<Tone, string> = {
  info: 'border-blue-200 bg-blue-50 text-blue-800',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-red-200 bg-red-50 text-red-800',
  neutral: 'border-gray-200 bg-gray-50 text-gray-700',
};

const iconToneClass: Record<Tone, string> = {
  info: 'bg-blue-50 text-blue-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  danger: 'bg-red-50 text-red-700',
  neutral: 'bg-gray-50 text-gray-700',
};

export function ModalSubtitle({ children }: { children: ReactNode }) {
  return <p className="mb-4 text-sm leading-6 text-gray-500">{children}</p>;
}

export function SummaryCard({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <Panel as="div" className={['bg-gray-50 shadow-none', className].join(' ')}>
      <PanelBody className="space-y-3 p-4">{children}</PanelBody>
    </Panel>
  );
}

export function MetaRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="min-w-0 text-right font-semibold text-gray-950">{value}</span>
    </div>
  );
}

export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: Tone }) {
  const Icon = tone === 'danger' || tone === 'warning' ? AlertTriangle : Info;

  return (
    <div className={['flex items-start gap-3 rounded-lg border px-3 py-2 text-sm', noticeToneClass[tone]].join(' ')}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 leading-6">{children}</div>
    </div>
  );
}

export function IconCircle({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return (
    <div className={['mb-3 inline-flex size-11 items-center justify-center rounded-full', iconToneClass[tone]].join(' ')}>
      {children}
    </div>
  );
}

export function AccountStatusBadge({ status }: { status: AccountConnectionStatus }) {
  if (status === 'connected') return <Badge tone="success">подключён</Badge>;
  if (status === 'needs_reconnect') return <Badge tone="warning">нужно переподключить</Badge>;
  if (status === 'disabled') return <Badge tone="neutral">отключён</Badge>;
  return <Badge tone="neutral">не подключён</Badge>;
}

export function QueueStatusBadge({ status }: { status: QueueItemStatus }) {
  if (status === 'ready') return <Badge tone="success">готов</Badge>;
  if (status === 'needs_review') return <Badge tone="danger">нужно исправить</Badge>;
  if (status === 'blocked') return <Badge tone="danger">заблокирован</Badge>;
  return <Badge tone="info">в запуске</Badge>;
}

export function ValidationStateIcon({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="size-4 text-emerald-600" aria-hidden="true" />
  ) : (
    <XCircle className="size-4 text-red-600" aria-hidden="true" />
  );
}
