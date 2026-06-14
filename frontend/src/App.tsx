import React, { useEffect, useRef, useState } from 'react';
import { Loader2, Lock, Play, ShieldCheck } from 'lucide-react';
import { api } from './api';
import { JobEvent, PipelineState, QuizGroup, SourceGroupSummary, TaskStatus, ValidationReport } from './types';
import Sidebar from './components/Sidebar';
import ImportScreen from './components/ImportScreen';
import MonitorScreen from './components/MonitorScreen';
import EditorScreen from './components/EditorScreen';
import DeployScreen from './components/DeployScreen';

const idlePipeline: PipelineState = {
  status: 'idle',
  progress: 0,
  currentGroup: '',
  currentStep: '',
  eta: 0,
  logs: [],
  warningsFound: [],
  result: null,
};

const defaultWorkspaceConfig = {
  workspaceDir: '.',
  sourcePath: 'questions_v2.json',
  outputDir: 'quizzes',
  mediaRoot: '.',
};

function taskStatusForJob(type: string, fallback: TaskStatus): TaskStatus {
  if (type.includes('parse')) return 'parsing';
  if (type.includes('generate')) return 'normalizing';
  if (type.includes('validate')) return 'validating';
  if (type.includes('upload')) return 'uploading';
  return fallback;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('import');
  const [quizGroups, setQuizGroups] = useState<QuizGroup[]>([]);
  const [sourceGroups, setSourceGroups] = useState<SourceGroupSummary[]>([]);
  const [generationQueue, setGenerationQueue] = useState<SourceGroupSummary[]>([]);
  const [workspaceConfig, setWorkspaceConfig] = useState(defaultWorkspaceConfig);
  const [pipeline, setPipeline] = useState<PipelineState>(idlePipeline);
  const activeEventSource = useRef<EventSource | null>(null);
  const activeJobStatus = useRef<TaskStatus>('idle');

  const refreshGroups = async () => {
    try {
      setQuizGroups(await api.getGroups());
    } catch (error) {
      console.error(error);
    }
  };

  const refreshSourceGroups = async () => {
    try {
      setSourceGroups(await api.getSourceGroups());
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    refreshGroups();
    refreshSourceGroups();
    return () => activeEventSource.current?.close();
  }, []);

  const applyJobEvent = (event: JobEvent) => {
    const running = event.status === 'running';
    const nextStatus = running ? taskStatusForJob(event.type, activeJobStatus.current) : 'idle';
    setPipeline((prev) => ({
      ...prev,
      status: nextStatus,
      progress: event.progress,
      currentGroup: event.current_group,
      currentStep: event.current_step,
      eta: event.eta,
      logs: [...prev.logs, event.log],
      warningsFound: event.warnings,
      activeJobId: event.job_id,
      error: event.error,
      result: event.result || prev.result,
    }));

    if (!running) {
      activeEventSource.current?.close();
      activeEventSource.current = null;
      refreshGroups();
      refreshSourceGroups();
    }
  };

  const watchJob = (jobId: string, status: TaskStatus, groupName: string) => {
    activeEventSource.current?.close();
    activeJobStatus.current = status;
    setPipeline({
      ...idlePipeline,
      status,
      currentGroup: groupName,
      currentStep: 'Подключение к backend job...',
      activeJobId: jobId,
    });
    setActiveTab('monitor');
    activeEventSource.current = api.subscribeJob(
      jobId,
      applyJobEvent,
      () => {
        activeEventSource.current?.close();
        activeEventSource.current = null;
      },
    );
  };

  const parseDocx = async (file: File, title: string, description: string, workspaceDir: string) => {
    const normalizedWorkspace = workspaceDir.trim() || '.';
    setWorkspaceConfig({
      workspaceDir: normalizedWorkspace,
      sourcePath: normalizedWorkspace === '.' ? 'questions_v2.json' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/questions_v2.json`,
      outputDir: normalizedWorkspace === '.' ? 'quizzes' : `${normalizedWorkspace.replace(/[\\/]+$/, '')}/quizzes`,
      mediaRoot: normalizedWorkspace,
    });
    const response = await api.parseDocx(file, title, description, normalizedWorkspace);
    watchJob(response.job_id, 'parsing', title);
  };

  const generateAllGroups = async (options: {
    model: string;
    outputDir: string;
    mediaRoot: string;
    styleExamples: number;
    maxRetries: number;
    groups?: string[];
    skipExisting?: boolean;
    sourcePath?: string;
    workspaceDir?: string;
  }) => {
    setWorkspaceConfig((current) => ({
      workspaceDir: options.workspaceDir || current.workspaceDir,
      sourcePath: options.sourcePath || current.sourcePath,
      outputDir: options.outputDir,
      mediaRoot: options.mediaRoot,
    }));
    const response = await api.generateAllGroups({
      source_path: options.sourcePath,
      output_dir: options.outputDir,
      groups: options.groups,
      skip_existing: options.skipExisting ?? true,
      model: options.model,
      media_root: options.mediaRoot,
      style_examples: options.styleExamples,
      max_retries: options.maxRetries,
    });
    watchJob(response.job_id, 'normalizing', options.groups?.length ? 'Очередь генерации' : 'Все группы');
  };

  const generateAllGroupsWithDefaults = () =>
    generateAllGroups({
      model: 'gpt-4.1-mini',
      outputDir: workspaceConfig.outputDir,
      mediaRoot: workspaceConfig.mediaRoot,
      styleExamples: 5,
      maxRetries: 3,
      sourcePath: workspaceConfig.sourcePath,
      workspaceDir: workspaceConfig.workspaceDir,
    });

  const queueGroupForGeneration = (group: SourceGroupSummary) => {
    if (group.generated) return;
    setGenerationQueue((current) => (
      current.some((item) => item.name === group.name) ? current : [...current, group]
    ));
  };

  const queueAllMissingGroups = () => {
    setGenerationQueue((current) => {
      const next = [...current];
      sourceGroups
        .filter((group) => !group.generated)
        .forEach((group) => {
          if (!next.some((item) => item.name === group.name)) next.push(group);
        });
      return next;
    });
  };

  const removeQueuedGroup = (groupName: string) => {
    setGenerationQueue((current) => current.filter((group) => group.name !== groupName));
  };

  const clearGenerationQueue = () => setGenerationQueue([]);

  const startGenerationQueue = async () => {
    if (generationQueue.length === 0) return;
    await generateAllGroups({
      model: 'gpt-4.1-mini',
      outputDir: workspaceConfig.outputDir,
      mediaRoot: workspaceConfig.mediaRoot,
      styleExamples: 5,
      maxRetries: 3,
      groups: generationQueue.map((group) => group.name),
      skipExisting: true,
      sourcePath: workspaceConfig.sourcePath,
      workspaceDir: workspaceConfig.workspaceDir,
    });
    setGenerationQueue([]);
  };

  const validateGroup = async (groupId: string, strict: boolean): Promise<ValidationReport> => {
    const response = await api.validateGroup(groupId, strict);
    const snapshot = await api.waitForJob(response.job_id);
    refreshGroups();
    if (snapshot.status === 'failed') {
      throw new Error(snapshot.error || 'Validation failed');
    }
    return snapshot.result?.report as ValidationReport;
  };

  const uploadGroup = async (options: {
    groupId: string;
    name: string;
    speed: 'normal' | 'fast';
    contextMode: 'once' | 'per_question';
    shuffleOptions: boolean;
  }) => {
    const response = await api.uploadGroup({
      group_id: options.groupId,
      name: options.name,
      speed: options.speed,
      context_send_mode: options.contextMode === 'per_question' ? 'per-question' : 'once',
      shuffle_options: options.shuffleOptions,
    });
    watchJob(response.job_id, 'uploading', options.name);
  };

  const uploadQueue = async (options: {
    items: Array<{ groupId: string; name: string }>;
    speed: 'normal' | 'fast';
    contextMode: 'once' | 'per_question';
    shuffleOptions: boolean;
  }) => {
    const response = await api.uploadQueue({
      items: options.items.map((item) => ({ group_id: item.groupId, name: item.name })),
      speed: options.speed,
      context_send_mode: options.contextMode === 'per_question' ? 'per-question' : 'once',
      shuffle_options: options.shuffleOptions,
    });
    watchJob(response.job_id, 'uploading', `Очередь Telegram (${options.items.length})`);
  };

  const cancelPipeline = async () => {
    if (!pipeline.activeJobId) return;
    await api.cancelJob(pipeline.activeJobId);
  };

  const handleTabChange = (tabId: string) => {
    if (pipeline.status !== 'idle' && tabId !== 'monitor') {
      alert(`Запущен фоновый процесс. Следите за прогрессом во вкладке "Мониторинг задач".`);
      setActiveTab('monitor');
      return;
    }
    setActiveTab(tabId);
  };

  const handleUpdateGroup = async (groupId: string, updatedGroup: QuizGroup) => {
    const saved = await api.saveGroup({ ...updatedGroup, id: groupId });
    setQuizGroups((groups) => groups.map((group) => (group.id === groupId ? saved : group)));
  };

  const uploadMedia = async (file: File): Promise<string> => {
    const uploaded = await api.uploadMedia(file);
    return uploaded.path;
  };

  const isLocked = pipeline.status !== 'idle';

  return (
    <div className="flex bg-slate-50 min-h-screen text-slate-800 antialiased font-sans">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={handleTabChange}
        status={pipeline.status}
        currentStep={pipeline.currentStep}
      />

      <main className="flex-1 flex flex-col min-w-0 max-w-7xl mx-auto">
        <header className="bg-white border-b border-slate-200 px-8 py-4 flex items-center justify-between shrink-0 select-none shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
          <h2 className="text-sm font-bold text-slate-800 tracking-tight flex items-center gap-2">
            <span>Панель управления</span>
            <span className="text-slate-300 text-xs">/</span>
            <span className="text-slate-500 font-medium font-sans">
              {activeTab === 'import' && 'Шаг 1: Загрузка и первичный парсинг'}
              {activeTab === 'monitor' && 'Шаг 2: Мониторинг фоновых процессов'}
              {activeTab === 'editor' && 'Шаг 3: Визуальный редактор квизов'}
              {activeTab === 'deploy' && 'Шаг 4: Деплой и загрузка'}
            </span>
          </h2>

          <div className="flex items-center gap-4">
            {isLocked ? (
              <div className="flex items-center gap-2 text-xs font-semibold px-4 py-1.5 rounded-xl bg-amber-500/10 text-amber-700 border border-amber-500/20 animate-pulse">
                <Loader2 size={14} className="animate-spin text-amber-600" />
                <span className="font-sans font-bold">ВЫПОЛНЯЕТСЯ BACKEND JOB...</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs font-semibold px-4 py-1.5 rounded-xl bg-emerald-500/10 text-emerald-800 border border-emerald-500/20">
                <ShieldCheck size={14} className="text-emerald-600" />
                <span>ОЧЕРЕДЬ СВОБОДНА</span>
              </div>
            )}
            <div className="h-6 w-px bg-slate-200" />
            <div className="text-[11px] font-mono text-slate-450 text-right shrink-0">
              <span className="block text-slate-400">API: LOCALHOST</span>
              <span className="block font-bold text-indigo-600">PORT 8000</span>
            </div>
          </div>
        </header>

        <section className="flex-1 p-8 overflow-y-auto space-y-6">
          {isLocked && activeTab !== 'monitor' && (
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 flex items-center justify-between gap-4 animate-slideDown shadow-sm">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-amber-100 rounded-xl text-amber-700 shrink-0">
                  <Lock size={16} />
                </div>
                <div>
                  <h4 className="font-bold text-amber-800 text-sm">Глобальный замок состояния</h4>
                  <p className="text-xs text-amber-600 leading-relaxed mt-0.5">
                    Backend job выполняется прямо сейчас. Повторные запуски и редактирование заблокированы до завершения.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setActiveTab('monitor')}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-bold text-xs rounded-xl shadow-md shadow-amber-600/15 transition flex items-center gap-1 shrink-0"
              >
                <span>В терминал логов</span>
                <Play size={10} className="fill-current text-white shrink-0" />
              </button>
            </div>
          )}

          <div className={`${isLocked && activeTab !== 'monitor' ? 'pointer-events-none opacity-50 select-none' : ''} transition-all`}>
            {activeTab === 'import' && (
              <ImportScreen
                status={pipeline.status}
                onParseDocx={parseDocx}
                onGenerateAllGroups={generateAllGroups}
              />
            )}
            {activeTab === 'monitor' && (
              <MonitorScreen
                pipeline={pipeline}
                cancelPipeline={cancelPipeline}
                setActiveTab={setActiveTab}
                onGenerateAllGroups={generateAllGroupsWithDefaults}
              />
            )}
            {activeTab === 'editor' && (
              <EditorScreen
                status={pipeline.status}
                quizGroups={quizGroups}
                sourceGroups={sourceGroups}
                generationQueue={generationQueue}
                onGenerateAllGroups={generateAllGroupsWithDefaults}
                queueGroupForGeneration={queueGroupForGeneration}
                queueAllMissingGroups={queueAllMissingGroups}
                removeQueuedGroup={removeQueuedGroup}
                clearGenerationQueue={clearGenerationQueue}
                startGenerationQueue={startGenerationQueue}
                uploadMedia={uploadMedia}
                updateQuizGroup={handleUpdateGroup}
              />
            )}
            {activeTab === 'deploy' && (
              <DeployScreen
                status={pipeline.status}
                quizGroups={quizGroups}
                validateGroup={validateGroup}
                uploadGroup={uploadGroup}
                uploadQueue={uploadQueue}
                updateQuizGroup={handleUpdateGroup}
              />
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
