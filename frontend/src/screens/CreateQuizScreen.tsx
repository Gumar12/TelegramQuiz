import {
  FileText,
  PencilLine,
  Trash2,
  Upload,
} from 'lucide-react';
import { useRef, useState, type ChangeEvent, type DragEvent, type ReactNode } from 'react';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';
import type { TaskStatus } from '../types';

export type CreateQuizFormValues = {
  title: string;
  useAiParsing: boolean;
  workspaceDir: string;
};

export type CreateQuizScreenProps = {
  initialValues?: Partial<CreateQuizFormValues>;
  jobError?: string;
  jobProgress?: number;
  jobStep?: string;
  onCancel?: () => void;
  onCreateFromDocx?: (file: File, title: string, description: string, workspaceDir: string, useAiParsing: boolean) => Promise<void> | void;
  onCreateFromJson?: (file: File, title: string, description: string, workspaceDir: string) => Promise<void> | void;
  onCreateManual?: (title: string, workspaceDir: string) => Promise<void> | void;
  status?: TaskStatus | 'importing';
};

type SourceFileKind = 'docx' | 'json';

const DEFAULT_DOCX_DESCRIPTION = 'Создано из DOCX локальным парсером';
const AI_DOCX_DESCRIPTION = 'Создано из DOCX через ИИ-разметку';
const DEFAULT_JSON_DESCRIPTION = 'Импортировано из JSON';

const defaultValues: CreateQuizFormValues = {
  title: '',
  useAiParsing: false,
  workspaceDir: '.',
};

function normalizeWorkspaceDir(value: string): string {
  return value.trim() || '.';
}

function isDocx(file: File): boolean {
  return file.name.toLowerCase().endsWith('.docx');
}

function isJson(file: File): boolean {
  return file.name.toLowerCase().endsWith('.json') || file.type === 'application/json';
}

function sourceFileKind(file: File): SourceFileKind | null {
  if (isDocx(file)) return 'docx';
  if (isJson(file)) return 'json';
  return null;
}

function titleFromFileName(fileName: string): string {
  return fileName.replace(/\.[^.]+$/, '').trim();
}

function messageFromError(error: unknown): string {
  if (!(error instanceof Error)) return 'Не удалось создать квиз.';
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    // Keep plain error messages as-is.
  }
  return error.message || 'Не удалось создать квиз.';
}

export default function CreateQuizScreen({
  initialValues,
  jobError,
  jobProgress = 0,
  jobStep = '',
  onCancel,
  onCreateFromDocx,
  onCreateFromJson,
  onCreateManual,
  status = 'idle',
}: CreateQuizScreenProps) {
  const [mode, setMode] = useState<'document' | 'manual'>('document');
  const [dragActive, setDragActive] = useState(false);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [values, setValues] = useState<CreateQuizFormValues>({ ...defaultValues, ...initialValues });
  const [localBusy, setLocalBusy] = useState(false);
  const [localError, setLocalError] = useState('');

  const docInputRef = useRef<HTMLInputElement>(null);
  const isLocked = status !== 'idle' || localBusy;
  const normalizedWorkspace = normalizeWorkspaceDir(values.workspaceDir);
  const sourcePath = normalizedWorkspace === '.' ? 'questions_v2.json' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/questions_v2.json`;
  const outputDir = normalizedWorkspace === '.' ? 'quizzes' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/quizzes`;

  const updateValue = <K extends keyof CreateQuizFormValues>(key: K, value: CreateQuizFormValues[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
  };

  const handleDrag = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(event.type === 'dragenter' || event.type === 'dragover');
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);

    const droppedFile = event.dataTransfer.files?.[0];
    if (!droppedFile || isLocked) return;

    if (!sourceFileKind(droppedFile)) {
      window.alert('Поддерживается DOCX или JSON.');
      return;
    }

    setSourceFile(droppedFile);
    setValues((current) => ({ ...current, title: current.title || titleFromFileName(droppedFile.name) }));
  };

  const handleDocSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;
    if (!sourceFileKind(selectedFile)) {
      window.alert('Поддерживается DOCX или JSON.');
      event.target.value = '';
      return;
    }
    setSourceFile(selectedFile);
    setValues((current) => ({ ...current, title: current.title || titleFromFileName(selectedFile.name) }));
  };

  const clearActiveFile = () => {
    setSourceFile(null);
    if (docInputRef.current) docInputRef.current.value = '';
  };

  const handleContinue = async () => {
    setLocalError('');
    if (mode === 'manual') {
      if (!onCreateManual) return;
      setLocalBusy(true);
      try {
        await onCreateManual(values.title.trim() || 'Новый квиз', normalizedWorkspace);
      } catch (error) {
        setLocalError(messageFromError(error));
      } finally {
        setLocalBusy(false);
      }
      return;
    }

    if (!sourceFile) {
      window.alert('Выберите DOCX или JSON файл.');
      return;
    }
    const kind = sourceFileKind(sourceFile);
    if (!kind) {
      window.alert('Поддерживается DOCX или JSON.');
      return;
    }

    if (kind === 'docx' && !onCreateFromDocx) {
      return;
    }
    if (kind === 'json' && !onCreateFromJson) {
      return;
    }

    setLocalBusy(true);
    try {
      const title = values.title.trim() || titleFromFileName(sourceFile.name);
      if (kind === 'docx') {
        await onCreateFromDocx?.(
          sourceFile,
          title,
          values.useAiParsing ? AI_DOCX_DESCRIPTION : DEFAULT_DOCX_DESCRIPTION,
          normalizedWorkspace,
          values.useAiParsing,
        );
      } else {
        await onCreateFromJson?.(sourceFile, title, DEFAULT_JSON_DESCRIPTION, normalizedWorkspace);
      }
    } catch (error) {
      setLocalError(messageFromError(error));
    } finally {
      setLocalBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-normal text-gray-950">Создание квиза</h1>
        <p className="text-sm leading-6 text-gray-600">Выберите источник и подготовьте квиз к редактированию.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <SourceCard
          active={mode === 'document'}
          description="DOCX или JSON"
          icon={<FileText className="size-12" aria-hidden="true" />}
          onSelect={() => {
            setMode('document');
            docInputRef.current?.click();
          }}
          title="Создать из документа"
          buttonLabel="Загрузить файл"
        />
        <SourceCard
          active={mode === 'manual'}
          description="Пустой квиз"
          icon={<PencilLine className="size-12" aria-hidden="true" />}
          onSelect={() => {
            setMode('manual');
          }}
          title="Создать вручную"
          buttonLabel="Выбрать"
        />
      </div>

      <input
        accept=".docx,.json,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        disabled={isLocked}
        onChange={handleDocSelect}
        ref={docInputRef}
        type="file"
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        {mode === 'document' ? (
          <div
            className={[
              'flex min-h-[300px] flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center transition-colors',
              dragActive ? 'border-[#E85D8F] bg-[#FCE7F0]/60' : 'border-gray-300 bg-white',
              isLocked ? 'opacity-60' : 'cursor-pointer hover:border-[#E85D8F]',
            ].join(' ')}
            onClick={() => {
              if (isLocked) return;
              docInputRef.current?.click();
            }}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            <Upload className="size-12 text-gray-500" aria-hidden="true" />
            <p className="mt-5 text-xl font-bold tracking-normal text-gray-950">Перетащите файл сюда</p>
            <p className="mt-2 text-sm text-gray-500">или выберите файл через кнопку выше</p>

            {sourceFile && (
              <div className="mt-6 flex w-full max-w-sm flex-col items-center gap-3">
                <div className="flex min-h-12 w-full items-center justify-center gap-3 rounded-md border border-gray-200 bg-white px-4 text-left shadow-sm">
                  <FileText className="size-5 shrink-0 text-blue-700" aria-hidden="true" />
                  <span className="truncate font-semibold text-gray-950">{sourceFile.name}</span>
                </div>
                <Button
                  icon={<Trash2 className="size-4" aria-hidden="true" />}
                  onClick={(event) => {
                    event.stopPropagation();
                    clearActiveFile();
                  }}
                  size="sm"
                  variant="subtle"
                >
                  Удалить
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex min-h-[300px] flex-col items-center justify-center rounded-lg border border-gray-200 bg-white p-6 text-center">
            <PencilLine className="size-12 text-gray-500" aria-hidden="true" />
            <p className="mt-5 text-xl font-bold tracking-normal text-gray-950">Пустой редактор</p>
            <p className="mt-2 max-w-md text-sm leading-6 text-gray-500">
              Будет создан пустой JSON-файл, после этого откроется редактор для добавления вопросов.
            </p>
          </div>
        )}

        <Panel>
          <PanelHeader title="Параметры" />
          <PanelBody className="space-y-4 pt-4">
            <Field label="Название квиза">
              <input
                className="min-h-10 w-full rounded-md border border-gray-300 px-3 text-sm text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
                disabled={isLocked}
                onChange={(event) => updateValue('title', event.target.value)}
                value={values.title}
              />
            </Field>

            <Field label="Рабочая папка">
              <input
                className="min-h-10 w-full rounded-md border border-gray-300 px-3 text-sm text-gray-950 outline-none transition focus:border-[#E85D8F] focus:ring-2 focus:ring-[#FCE7F0]"
                disabled={isLocked}
                onChange={(event) => updateValue('workspaceDir', event.target.value)}
                value={values.workspaceDir}
              />
            </Field>

            {mode === 'document' && (!sourceFile || sourceFileKind(sourceFile) !== 'json') && (
              <ToggleRow
                checked={values.useAiParsing}
                disabled={isLocked}
                label="ИИ-разметка"
                onChange={(checked) => updateValue('useAiParsing', checked)}
              />
            )}

            <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-xs leading-5 text-gray-600">
              {mode === 'document' && (
                <p>
                  JSON источника: <span className="font-mono text-gray-900">{sourcePath}</span>
                </p>
              )}
              <p>
                Готовые квизы: <span className="font-mono text-gray-900">{outputDir}</span>
              </p>
            </div>
          </PanelBody>
        </Panel>
      </div>

      <Panel>
        <PanelBody className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          {onCancel && (
            <Button onClick={onCancel} variant="subtle">
              Отменить
            </Button>
          )}
          <Button
            loading={isLocked}
            onClick={handleContinue}
            variant="primary"
          >
            {mode === 'manual' ? 'Создать вручную' : sourceFile && sourceFileKind(sourceFile) === 'json' ? 'Импортировать JSON' : 'Создать JSON'}
          </Button>
        </PanelBody>
      </Panel>

      {(status !== 'idle' || jobError || localError) && (
        <Panel>
        <PanelBody className="space-y-3">
            {status !== 'idle' && (
              <div>
                <div className="flex items-center justify-between gap-4 text-sm font-semibold text-gray-800">
                  <span>{jobStep || 'Backend job выполняется'}</span>
                  <span>{Math.max(0, Math.min(100, Math.round(jobProgress)))}%</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-[#E85D8F] transition-all"
                    style={{ width: `${Math.max(0, Math.min(100, jobProgress))}%` }}
                  />
                </div>
              </div>
            )}

            {(jobError || localError) && (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                {jobError || localError}
              </div>
            )}
          </PanelBody>
        </Panel>
      )}
    </div>
  );
}

function SourceCard({
  active,
  buttonLabel,
  description,
  icon,
  onSelect,
  title,
}: {
  active: boolean;
  buttonLabel: string;
  description: string;
  icon: ReactNode;
  onSelect: () => void;
  title: string;
}) {
  return (
    <Panel
      as="article"
      className={[
        'transition-colors',
        active ? 'border-[#E85D8F] bg-[#FCE7F0]/30' : 'hover:border-gray-300',
      ].join(' ')}
    >
      <PanelBody className="flex min-h-[130px] items-center gap-5">
        <div className="shrink-0 text-gray-500 [&_svg]:size-9">{icon}</div>
        <div className="min-w-0">
          <h2 className="text-lg font-bold tracking-normal text-gray-950">{title}</h2>
          <p className="mt-1 text-sm text-gray-500">{description}</p>
          <Button className="mt-4" onClick={onSelect} size="sm" variant="outline">
            {buttonLabel}
          </Button>
        </div>
      </PanelBody>
    </Panel>
  );
}

function Field({ children, label }: { children: ReactNode; label: string }) {
  return (
    <label className="block space-y-1.5 text-sm font-semibold text-gray-800">
      <span>{label}</span>
      {children}
    </label>
  );
}

function ToggleRow({
  checked,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 items-center justify-between gap-4 rounded-md border border-gray-200 px-3 py-2">
      <span className="text-sm font-semibold text-gray-950">{label}</span>
      <button
        aria-checked={checked}
        className={[
          'relative h-7 w-12 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E85D8F] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60',
          checked ? 'bg-[#E85D8F]' : 'bg-gray-200',
        ].join(' ')}
        disabled={disabled}
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
