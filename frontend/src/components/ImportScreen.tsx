import React, { useMemo, useRef, useState } from 'react';
import {
  Database,
  FileText,
  FileUp,
  FolderOpen,
  Image,
  ListRestart,
  Loader2,
  Play,
  Settings,
} from 'lucide-react';
import { TaskStatus } from '../types';

interface ImportScreenProps {
  status: TaskStatus;
  onParseDocx: (file: File, title: string, description: string, workspaceDir: string) => Promise<void>;
  onGenerateAllGroups: (options: {
    model: string;
    outputDir: string;
    mediaRoot: string;
    styleExamples: number;
    maxRetries: number;
    sourcePath?: string;
    workspaceDir?: string;
  }) => Promise<void>;
}

const DEFAULT_DESCRIPTION = 'Сгенерировано из импортированного документа';

function normalizeWorkspaceDir(value: string): string {
  return value.trim() || '.';
}

function joinPath(root: string, child: string): string {
  const normalized = normalizeWorkspaceDir(root);
  if (normalized === '.') return child;
  return `${normalized.replace(/[\\/]+$/, '')}/${child}`;
}

export default function ImportScreen({ status, onParseDocx, onGenerateAllGroups }: ImportScreenProps) {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [quizName, setQuizName] = useState('История Казахстана');
  const [workspaceDir, setWorkspaceDir] = useState('.');
  const [model, setModel] = useState('gpt-4.1-mini');
  const [styleExamples, setStyleExamples] = useState(5);
  const [maxRetries, setMaxRetries] = useState(3);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const isLocked = status !== 'idle';
  const normalizedWorkspace = normalizeWorkspaceDir(workspaceDir);

  const paths = useMemo(() => ({
    sourceJson: joinPath(normalizedWorkspace, 'questions_v2.json'),
    mediaDir: joinPath(normalizedWorkspace, 'media'),
    outputDir: joinPath(normalizedWorkspace, 'quizzes'),
  }), [normalizedWorkspace]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile.name.endsWith('.docx')) {
        setFile(droppedFile);
      } else {
        alert('Пожалуйста, загрузите файл DOCX.');
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleManualConvert = async () => {
    if (!file) {
      alert('Пожалуйста, загрузите DOCX файл.');
      return;
    }

    await onParseDocx(file, quizName, DEFAULT_DESCRIPTION, normalizedWorkspace);
  };

  const handleGenerateAllGroups = async () => {
    await onGenerateAllGroups({
      model,
      outputDir: paths.outputDir,
      mediaRoot: normalizedWorkspace,
      styleExamples,
      maxRetries,
      sourcePath: paths.sourceJson,
      workspaceDir: normalizedWorkspace,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Шаг 1: Импорт DOCX</h2>
        <p className="text-slate-500 text-sm mt-1">
          Выберите документ, рабочую папку и запустите создание исходного JSON или готовых JSON по группам.
        </p>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-100">
          <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
            <FileUp size={16} className="text-indigo-600" />
            Исходный DOCX
          </h3>
        </div>

        <div className="p-6">
          <div
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => !isLocked && fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all flex flex-col items-center justify-center cursor-pointer min-h-36 ${
              dragActive
                ? 'border-indigo-500 bg-indigo-50/50'
                : 'border-slate-200 hover:border-slate-350 bg-slate-50/55'
            } ${isLocked ? 'pointer-events-none opacity-50' : ''}`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              className="hidden"
              accept=".docx"
              disabled={isLocked}
            />
            <div className="p-3 bg-white shadow-sm border border-slate-100 rounded-xl text-slate-400 mb-3">
              <FileUp size={28} className="text-indigo-500" />
            </div>
            {file ? (
              <div className="space-y-1">
                <p className="font-semibold text-slate-850 text-sm flex items-center justify-center gap-1 text-emerald-600">
                  <FileText size={16} /> {file.name}
                </p>
                <p className="text-xs text-slate-400 font-mono">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="font-semibold text-slate-850 text-sm">Перетащите DOCX файл сюда</p>
                <p className="text-xs text-slate-400">или нажмите для выбора файла на диске</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-5">
        <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
          <FolderOpen size={16} className="text-indigo-600" />
          Куда сохранять
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          <div className="space-y-1.5">
            <label className="text-slate-500 block font-semibold">Название источника</label>
            <input
              type="text"
              value={quizName}
              onChange={(e) => setQuizName(e.target.value)}
              disabled={isLocked}
              className="w-full text-slate-850 p-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-slate-500 block font-semibold">Рабочая папка</label>
            <input
              type="text"
              value={workspaceDir}
              onChange={(e) => setWorkspaceDir(e.target.value)}
              disabled={isLocked}
              placeholder="например: runs/19_may или C:/Quizbot/runs/19_may"
              className="w-full text-slate-850 p-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 min-w-0">
            <div className="flex items-center gap-2 text-slate-500 font-semibold mb-1">
              <Database size={14} />
              Исходный JSON
            </div>
            <p className="font-mono text-slate-700 break-all">{paths.sourceJson}</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 min-w-0">
            <div className="flex items-center gap-2 text-slate-500 font-semibold mb-1">
              <Image size={14} />
              Картинки
            </div>
            <p className="font-mono text-slate-700 break-all">{paths.mediaDir}</p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 min-w-0">
            <div className="flex items-center gap-2 text-slate-500 font-semibold mb-1">
              <FileText size={14} />
              Готовые JSON
            </div>
            <p className="font-mono text-slate-700 break-all">{paths.outputDir}</p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-5">
        <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
          <Settings size={16} className="text-indigo-600" />
          GPT-нормализация
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="space-y-1.5">
            <label className="text-slate-500 block font-semibold">OpenAI model</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={isLocked}
              className="w-full text-slate-850 p-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-slate-500 block font-semibold">Style examples</label>
            <input
              type="number"
              min={0}
              value={styleExamples}
              onChange={(e) => setStyleExamples(Number(e.target.value))}
              disabled={isLocked}
              className="w-full text-slate-850 p-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-slate-500 block font-semibold">Max retries</label>
            <input
              type="number"
              min={1}
              value={maxRetries}
              onChange={(e) => setMaxRetries(Number(e.target.value))}
              disabled={isLocked}
              className="w-full text-slate-850 p-2.5 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="text-xs text-slate-500">
          {isLocked ? (
            <span className="inline-flex items-center gap-2 text-amber-700 font-semibold">
              <Loader2 size={14} className="animate-spin" />
              Сейчас выполняется задача. Прогресс открыт в мониторинге.
            </span>
          ) : (
            <span>Сначала разберите DOCX, затем создайте готовые JSON по найденным группам.</span>
          )}
        </div>

        <div className="flex flex-col sm:flex-row gap-3">
          <button
            type="button"
            onClick={handleManualConvert}
            disabled={isLocked || !file}
            className={`px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-sm font-semibold transition ${
              isLocked || !file
                ? 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-500/10'
            }`}
          >
            {status === 'parsing' ? (
              <>
                <Loader2 size={18} className="animate-spin text-white" />
                Разбор DOCX...
              </>
            ) : (
              <>
                <Play size={18} />
                Разобрать DOCX
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleGenerateAllGroups}
            disabled={isLocked}
            className={`px-4 py-3 rounded-xl flex items-center justify-center gap-2 text-sm font-semibold transition ${
              isLocked
                ? 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg shadow-emerald-500/10'
            }`}
          >
            {status === 'normalizing' ? (
              <>
                <Loader2 size={18} className="animate-spin text-white" />
                Создание JSON...
              </>
            ) : (
              <>
                <ListRestart size={18} />
                Создать JSON по всем группам
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
