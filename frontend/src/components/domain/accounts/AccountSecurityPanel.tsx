import { Plus, ShieldCheck } from 'lucide-react';
import { Button } from '../../ui/Button';
import { Panel, PanelBody, PanelHeader } from '../../ui/Panel';

type AccountSecurityPanelProps = {
  connectionActionsEnabled?: boolean;
  onAddTelegram?: () => void;
};

export function AccountSecurityPanel({ connectionActionsEnabled = false, onAddTelegram }: AccountSecurityPanelProps) {
  const canAdd = connectionActionsEnabled && Boolean(onAddTelegram);

  return (
    <div className="space-y-5">
      {canAdd && (
        <Panel>
          <PanelHeader title="Подключить аккаунт" />
          <PanelBody className="space-y-5 pt-4">
            <p className="text-base leading-7 text-gray-600">Добавьте Telegram-аккаунт для запуска квизов.</p>
            <Button
              className="w-full"
              icon={<Plus className="size-5" aria-hidden="true" />}
              onClick={onAddTelegram}
              variant="primary"
            >
              Добавить Telegram
            </Button>
          </PanelBody>
        </Panel>
      )}

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
    </div>
  );
}
