import { FolderOpen, RotateCcw, Save, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';

export type SettingsLaunchSpeed = 'normal' | 'fast';
export type SettingsContextMode = 'per-question' | 'once';
export type SettingsDuplicatePolicy = 'error' | 'warning' | 'review';

export type SettingsValues = {
  autosave: {
    enabled: boolean;
    intervalSec: number;
  };
  defaultLaunch: {
    contextMode: SettingsContextMode;
    quizBotResponseSec: number;
    segmentSize: number;
    shuffleOptions: boolean;
    speed: SettingsLaunchSpeed;
  };
  validation: {
    blockOnErrors: boolean;
    duplicatePolicy: SettingsDuplicatePolicy;
    showWarnings: boolean;
    strict: boolean;
  };
  workspaceLabel: string;
};

export type SettingsScreenProps = {
  onChooseWorkspace?: () => void;
  onClearTemporaryFiles?: () => void;
  onResetSettings?: () => void;
  onSaveSettings?: (settings: SettingsValues) => void | Promise<void>;
  onSettingsChange?: (settings: SettingsValues) => void;
  saving?: boolean;
  settings?: PartialSettingsValues;
  storageActionsEnabled?: boolean;
};

type PartialSettingsValues = Partial<
  Omit<SettingsValues, 'autosave' | 'defaultLaunch' | 'validation'> & {
    autosave: Partial<SettingsValues['autosave']>;
    defaultLaunch: Partial<SettingsValues['defaultLaunch']>;
    validation: Partial<SettingsValues['validation']>;
  }
>;

const defaultSettings: SettingsValues = {
  autosave: {
    enabled: true,
    intervalSec: 30,
  },
  defaultLaunch: {
    contextMode: 'per-question',
    quizBotResponseSec: 2,
    segmentSize: 50,
    shuffleOptions: false,
    speed: 'normal',
  },
  validation: {
    blockOnErrors: true,
    duplicatePolicy: 'error',
    showWarnings: true,
    strict: true,
  },
  workspaceLabel: 'data/runs',
};

const speedOptions: SettingsLaunchSpeed[] = ['normal', 'fast'];

const contextModeOptions: Array<{ label: string; value: SettingsContextMode }> = [
  { label: 'на каждый вопрос', value: 'per-question' },
  { label: 'один раз', value: 'once' },
];

const duplicatePolicyOptions: Array<{ label: string; value: SettingsDuplicatePolicy }> = [
  { label: 'ошибка', value: 'error' },
  { label: 'предупреждение', value: 'warning' },
  { label: 'ручная проверка', value: 'review' },
];

function mergeSettings(settings?: PartialSettingsValues): SettingsValues {
  return {
    ...defaultSettings,
    ...settings,
    autosave: { ...defaultSettings.autosave, ...settings?.autosave },
    defaultLaunch: { ...defaultSettings.defaultLaunch, ...settings?.defaultLaunch },
    validation: { ...defaultSettings.validation, ...settings?.validation },
  };
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.round(value)));
}

export default function SettingsScreen({
  onChooseWorkspace,
  onClearTemporaryFiles,
  onResetSettings,
  onSaveSettings,
  onSettingsChange,
  saving = false,
  settings,
  storageActionsEnabled = false,
}: SettingsScreenProps) {
  const initialSettings = useMemo(() => mergeSettings(settings), [settings]);
  const [draft, setDraft] = useState<SettingsValues>(initialSettings);
  const canSave = Boolean(onSaveSettings);
  const canChooseWorkspace = storageActionsEnabled && Boolean(onChooseWorkspace);
  const canClearTemporaryFiles = storageActionsEnabled && Boolean(onClearTemporaryFiles);

  useEffect(() => {
    setDraft(initialSettings);
  }, [initialSettings]);

  const updateDraft = (next: SettingsValues) => {
    setDraft(next);
    onSettingsChange?.(next);
  };

  const patchLaunch = (patch: Partial<SettingsValues['defaultLaunch']>) => {
    updateDraft({ ...draft, defaultLaunch: { ...draft.defaultLaunch, ...patch } });
  };

  const patchAutosave = (patch: Partial<SettingsValues['autosave']>) => {
    updateDraft({ ...draft, autosave: { ...draft.autosave, ...patch } });
  };

  const patchValidation = (patch: Partial<SettingsValues['validation']>) => {
    updateDraft({ ...draft, validation: { ...draft.validation, ...patch } });
  };

  const resetDraft = () => {
    updateDraft(initialSettings);
    onResetSettings?.();
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Настройки</h1>
        <p className="text-sm leading-6 text-gray-600">Поведение редактора, проверки и запусков по умолчанию.</p>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Запуск по умолчанию" />
          <PanelBody className="space-y-4 pt-4">
            <div className="grid gap-3 lg:grid-cols-[140px_minmax(0,1fr)] lg:items-center">
              <FieldLabel>Скорость</FieldLabel>
              <SegmentedControl
                onChange={(speed) => patchLaunch({ speed })}
                options={speedOptions}
                value={draft.defaultLaunch.speed}
              />

              <FieldLabel>Режим контекста</FieldLabel>
              <SelectField
                label="Режим контекста"
                onChange={(contextMode) => patchLaunch({ contextMode })}
                options={contextModeOptions}
                value={draft.defaultLaunch.contextMode}
              />

              <FieldLabel>Размер сегмента</FieldLabel>
              <NumberField
                max={500}
                min={1}
                onChange={(segmentSize) => patchLaunch({ segmentSize })}
                value={draft.defaultLaunch.segmentSize}
              />

              <FieldLabel>Ответ QuizBot, сек</FieldLabel>
              <NumberField
                max={30}
                min={0}
                onChange={(quizBotResponseSec) => patchLaunch({ quizBotResponseSec })}
                value={draft.defaultLaunch.quizBotResponseSec}
              />
            </div>
            <ToggleRow
              checked={draft.defaultLaunch.shuffleOptions}
              label="Перемешивать варианты"
              onChange={(shuffleOptions) => patchLaunch({ shuffleOptions })}
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Автосейв" />
          <PanelBody className="space-y-4 pt-4">
            <ToggleRow
              checked={draft.autosave.enabled}
              label="Автосейв включен"
              onChange={(enabled) => patchAutosave({ enabled })}
            />
            <div className="grid gap-3 lg:grid-cols-[140px_minmax(0,1fr)] lg:items-center">
              <FieldLabel>Интервал, сек</FieldLabel>
              <NumberField
                disabled={!draft.autosave.enabled}
                max={600}
                min={5}
                onChange={(intervalSec) => patchAutosave({ intervalSec })}
                value={draft.autosave.intervalSec}
              />
            </div>
            <p className="text-sm leading-6 text-gray-500">Последний автосейв показывается в редакторе.</p>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Проверка JSON" />
          <PanelBody className="space-y-3 pt-4">
            <ToggleRow
              checked={draft.validation.strict}
              label="Строгая проверка"
              onChange={(strict) => patchValidation({ strict })}
            />
            <ToggleRow
              checked={draft.validation.showWarnings}
              label="Показывать предупреждения"
              onChange={(showWarnings) => patchValidation({ showWarnings })}
            />
            <ToggleRow
              checked={draft.validation.blockOnErrors}
              label="Блокировать запуск при ошибках"
              onChange={(blockOnErrors) => patchValidation({ blockOnErrors })}
            />
            <div className="grid gap-3 pt-1 lg:grid-cols-[140px_minmax(0,1fr)] lg:items-center">
              <FieldLabel>Дубли вариантов</FieldLabel>
              <SelectField
                label="Дубли вариантов"
                onChange={(duplicatePolicy) => patchValidation({ duplicatePolicy })}
                options={duplicatePolicyOptions}
                value={draft.validation.duplicatePolicy}
              />
            </div>
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Файлы и хранение" />
          <PanelBody className="space-y-4 pt-4">
            <div className="grid gap-3 lg:grid-cols-[140px_minmax(0,1fr)] lg:items-center">
              <FieldLabel>Workspace</FieldLabel>
              <input
                className="min-h-11 w-full rounded-md border border-gray-200 bg-gray-50 px-3 text-sm font-semibold text-gray-700"
                readOnly
                type="text"
                value={draft.workspaceLabel}
              />
            </div>

            {(canChooseWorkspace || canClearTemporaryFiles) && (
              <div className="flex flex-wrap gap-3">
                {canChooseWorkspace && (
                  <Button
                    icon={<FolderOpen className="size-4" aria-hidden="true" />}
                    onClick={onChooseWorkspace}
                    variant="outline"
                  >
                    Выбрать папку
                  </Button>
                )}
                {canClearTemporaryFiles && (
                  <Button
                    icon={<Trash2 className="size-4" aria-hidden="true" />}
                    onClick={onClearTemporaryFiles}
                    variant="outline"
                  >
                    Очистить временные файлы
                  </Button>
                )}
              </div>
            )}
            <p className="text-sm leading-6 text-gray-500">
              Исходные документы и session-файлы не удаляются автоматически.
            </p>
          </PanelBody>
        </Panel>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        {canSave && (
          <Button
            icon={<Save className="size-4" aria-hidden="true" />}
            loading={saving}
            onClick={() => onSaveSettings?.(draft)}
            variant="primary"
          >
            Сохранить настройки
          </Button>
        )}
        <Button icon={<RotateCcw className="size-4" aria-hidden="true" />} onClick={resetDraft} variant="outline">
          Сбросить
        </Button>
      </div>
    </div>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="text-sm font-semibold text-gray-700">{children}</span>;
}

function NumberField({
  disabled = false,
  max,
  min,
  onChange,
  value,
}: {
  disabled?: boolean;
  max: number;
  min: number;
  onChange: (value: number) => void;
  value: number;
}) {
  return (
    <input
      className="min-h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0] disabled:bg-gray-50 disabled:text-gray-400"
      disabled={disabled}
      max={max}
      min={min}
      onChange={(event) => onChange(clampNumber(Number(event.target.value), min, max))}
      type="number"
      value={value}
    />
  );
}

function SegmentedControl<T extends string>({
  onChange,
  options,
  value,
}: {
  onChange: (value: T) => void;
  options: T[];
  value: T;
}) {
  return (
    <div
      className="grid rounded-md border border-gray-200 bg-gray-50 p-1"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map((option) => (
        <button
          className={[
            'min-h-9 rounded px-3 text-sm font-semibold transition-colors',
            value === option ? 'bg-white text-[#E85D8F] shadow-sm' : 'text-gray-600 hover:text-gray-950',
          ].join(' ')}
          key={option}
          onClick={() => onChange(option)}
          type="button"
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function SelectField<T extends string>({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: T) => void;
  options: Array<{ label: string; value: T }>;
  value: T;
}) {
  return (
    <select
      aria-label={label}
      className="min-h-10 w-full rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
      onChange={(event) => onChange(event.target.value as T)}
      value={value}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function ToggleRow({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 items-center justify-between gap-4 rounded-md border border-gray-200 px-3 py-2">
      <span className="text-sm font-semibold text-gray-950">{label}</span>
      <button
        aria-checked={checked}
        className={[
          'relative h-7 w-12 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E85D8F] focus-visible:ring-offset-2',
          checked ? 'bg-[#E85D8F]' : 'bg-gray-200',
        ].join(' ')}
        onClick={() => onChange(!checked)}
        role="switch"
        type="button"
      >
        <span
          className={[
            'absolute left-1 top-1 size-5 rounded-full bg-white shadow-sm transition-transform',
            checked ? 'translate-x-5' : 'translate-x-0',
          ].join(' ')}
        />
      </button>
    </label>
  );
}
