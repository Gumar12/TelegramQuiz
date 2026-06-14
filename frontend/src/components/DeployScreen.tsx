import React, { useState, useEffect } from 'react';
import { 
  SendToBack, 
  Settings2, 
  HelpCircle, 
  FileCheck2, 
  AlertTriangle, 
  CheckCircle2, 
  Info, 
  Play, 
  Copy, 
  ExternalLink,
  ChevronDown,
  Gauge,
  Loader2,
  Trash2
} from 'lucide-react';
import { QuizGroup, TaskStatus, ValidationReport } from '../types';

interface DeployScreenProps {
  status: TaskStatus;
  quizGroups: QuizGroup[];
  validateGroup: (groupId: string, strict: boolean) => Promise<ValidationReport>;
  uploadGroup: (options: {
    groupId: string;
    name: string;
    speed: 'normal' | 'fast';
    contextMode: 'once' | 'per_question';
    shuffleOptions: boolean;
  }) => Promise<void>;
  uploadQueue: (options: {
    items: Array<{ groupId: string; name: string }>;
    speed: 'normal' | 'fast';
    contextMode: 'once' | 'per_question';
    shuffleOptions: boolean;
  }) => Promise<void>;
  updateQuizGroup: (groupId: string, updatedGroup: QuizGroup) => void;
}

export default function DeployScreen({ status, quizGroups, validateGroup, uploadGroup, uploadQueue, updateQuizGroup }: DeployScreenProps) {
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [strictMode, setStrictMode] = useState<boolean>(false);
  const [validationReport, setValidationReport] = useState<any | null>(null);
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  // Deploy configuration parameters
  const [botTitle, setBotTitle] = useState('История Казахстана — Итоговый');
  const [uploadSpeed, setUploadSpeed] = useState<'normal' | 'fast'>('normal');
  const [contextMode, setContextMode] = useState<'once' | 'per_question'>('once');
  const [shuffleOptions, setShuffleOptions] = useState<boolean>(true);
  const [uploadCompleted, setUploadCompleted] = useState<boolean>(false);
  const [telegramQueue, setTelegramQueue] = useState<Array<{ groupId: string; name: string; questions: number }>>([]);

  useEffect(() => {
    if (quizGroups.length > 0 && !selectedGroupId) {
      setSelectedGroupId(quizGroups[0].id);
    }
  }, [quizGroups]);

  const activeGroup = quizGroups.find(g => g.id === selectedGroupId);

  const handleValidate = async () => {
    if (!activeGroup) return;
    setIsValidating(true);
    setUploadCompleted(false);

    try {
      const report = await validateGroup(activeGroup.id, strictMode);
      const totalQuestions = report.questions_total;
      const indexCounts = [0, 0, 0, 0];
      Object.entries(report.correct_position_counts || {}).forEach(([key, count]) => {
        const index = Number(key) - 1;
        if (index >= 0 && index < indexCounts.length) indexCounts[index] = Number(count);
      });
      const positionPercentages = indexCounts.map(count =>
        totalQuestions > 0 ? Math.round((count / totalQuestions) * 100) : 0
      );
      const warningsList = (report.warnings || []).map((warning: any) => {
        const index = warning.index ? `Вопрос #${warning.index}: ` : '';
        return `${index}${warning.message || warning.code || JSON.stringify(warning)}`;
      });
      const hasFailures = strictMode && warningsList.length > 0;
      setValidationReport({
        success: !hasFailures,
        totalQuestions,
        distribution: positionPercentages,
        warnings: warningsList,
        scannedAt: new Date().toLocaleTimeString()
      });
      if (warningsList.length === 0) {
        updateQuizGroup(selectedGroupId, { ...activeGroup, status: 'ready' });
      }
    } catch (error) {
      setValidationReport({
        success: false,
        totalQuestions: activeGroup.questions.length,
        distribution: [0, 0, 0, 0],
        warnings: [error instanceof Error ? error.message : String(error)],
        scannedAt: new Date().toLocaleTimeString()
      });
    } finally {
      setIsValidating(false);
    }
  };

  const handleDeployToTelegram = async () => {
    if (!activeGroup) return;
    await uploadGroup({
      groupId: activeGroup.id,
      name: botTitle || activeGroup.name,
      speed: uploadSpeed,
      contextMode,
      shuffleOptions,
    });
    setUploadCompleted(false);
  };

  const handleAddToTelegramQueue = () => {
    if (!activeGroup) return;
    setTelegramQueue((current) => (
      current.some((item) => item.groupId === activeGroup.id)
        ? current
        : [...current, { groupId: activeGroup.id, name: botTitle || activeGroup.name, questions: activeGroup.questions.length }]
    ));
  };

  const handleAddAllToTelegramQueue = () => {
    setTelegramQueue((current) => {
      const next = [...current];
      quizGroups.forEach((group) => {
        if (!next.some((item) => item.groupId === group.id)) {
          next.push({ groupId: group.id, name: group.name, questions: group.questions.length });
        }
      });
      return next;
    });
  };

  const handleRemoveFromTelegramQueue = (groupId: string) => {
    setTelegramQueue((current) => current.filter((item) => item.groupId !== groupId));
  };

  const handleStartTelegramQueue = async () => {
    if (telegramQueue.length === 0) return;
    await uploadQueue({
      items: telegramQueue.map((item) => ({ groupId: item.groupId, name: item.name })),
      speed: uploadSpeed,
      contextMode,
      shuffleOptions,
    });
    setTelegramQueue([]);
    setUploadCompleted(false);
  };

  const handleCopyLink = () => {
    navigator.clipboard.writeText('https://t.me/QuizBot?start=historical_kaz_studio_quiz_f58b');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isLocked = status !== 'idle';
  const canDeploy = Boolean(activeGroup);
  const activeQueued = activeGroup ? telegramQueue.some((item) => item.groupId === activeGroup.id) : false;

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Шаг 4: Валидация и загрузка в Telegram</h2>
        <p className="text-slate-500 text-sm mt-1">
          Запустите локальный тестер на соответствие лимитам API, настройте скорость выгрузки и запустите автоматический деплой в BOT-канал.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Validator and Quality Report */}
        <div className="lg:col-span-1 lg:order-2 space-y-6">
          
          {/* Validator Header Select Component */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
            <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
              <span className="w-1.5 h-3 bg-indigo-600 rounded-full" />
              Блок Б: Локальный валидатор качества квиза
            </h3>

            <div className="flex flex-col sm:flex-row gap-4 items-end sm:items-center justify-between text-xs">
              <div className="flex items-center gap-3">
                <span className="text-slate-450 font-bold font-mono">ГРУППА ДЛЯ ОЦЕНКИ:</span>
                <div className="relative">
                  <select
                    value={selectedGroupId}
                    onChange={(e) => {
                      setSelectedGroupId(e.target.value);
                      setValidationReport(null);
                    }}
                    disabled={isLocked}
                    className="appearance-none font-bold text-slate-800 bg-slate-50 border border-slate-210 rounded-xl px-4 py-2 pr-10 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
                  >
                    {quizGroups.map(g => (
                      <option key={g.id} value={g.id}>{g.name}</option>
                    ))}
                  </select>
                  <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                </div>
              </div>

              {/* Strict Toggle */}
              <label className="flex items-center gap-2 cursor-pointer select-none py-1 text-slate-600">
                <input
                  type="checkbox"
                  checked={strictMode}
                  onChange={(e) => {
                    setStrictMode(e.target.checked);
                    setValidationReport(null);
                  }}
                  disabled={isLocked}
                  className="rounded text-indigo-600 focus:ring-indigo-500 border-slate-300"
                />
                <span className="font-semibold">Строгий режим (--strict)</span>
              </label>
            </div>

            <button
              onClick={handleValidate}
              disabled={isLocked || !activeGroup || isValidating}
              className="w-full py-2.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-bold text-xs rounded-xl transition flex items-center justify-center gap-2"
            >
              {isValidating ? (
                <>
                  <Loader2 size={14} className="animate-spin text-slate-600" />
                  <span>Проверка синтаксиса на диске...</span>
                </>
              ) : (
                <>
                  <FileCheck2 size={14} className="text-indigo-600" />
                  <span>Запустить валидацию квиза</span>
                </>
              )}
            </button>
          </div>

          {/* Tester Quality Report Results */}
          {validationReport ? (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-5 animate-scaleUp">
              {/* Outcome Header Badge */}
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
                  <Info size={16} className="text-indigo-600" />
                  <span>Отчет валидации от {validationReport.scannedAt}</span>
                </div>

                {validationReport.warnings.length === 0 ? (
                  <span className="px-3 py-1 bg-emerald-100 text-emerald-800 rounded-full font-bold font-mono text-xs flex items-center gap-1">
                    <CheckCircle2 size={14} /> PASSED
                  </span>
                ) : validationReport.success ? (
                  <span className="px-3 py-1 bg-amber-100 text-amber-800 rounded-full font-bold font-mono text-xs flex items-center gap-1">
                    <AlertTriangle size={14} /> WARNINGS
                  </span>
                ) : (
                  <span className="px-3 py-1 bg-rose-100 text-rose-800 rounded-full font-bold font-mono text-xs flex items-center gap-1">
                    <AlertTriangle size={14} /> FAILED
                  </span>
                )}
              </div>

              {/* Position Distribution Analyzer Grid */}
              <div className="p-4 bg-slate-50 rounded-2xl border border-slate-200 space-y-3">
                <span className="text-[10px] text-slate-400 font-mono font-bold tracking-wider block">АНАЛИЗ РАСПРЕДЕЛЕНИЯ ПРАВИЛЬНЫХ ОТВЕТОВ (ПОДСТРАХОВКА БАЙАСОВ):</span>
                
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                  {validationReport.distribution.map((percentage: number, idx: number) => (
                    <div key={idx} className="space-y-1 bg-white p-2 rounded-xl border border-slate-100">
                      <span className="text-[10px] text-slate-450 block font-mono">Вариант #{idx + 1}</span>
                      <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden mt-1">
                        <div 
                          className={`h-full rounded-full ${percentage > 50 ? 'bg-amber-500' : 'bg-indigo-600'}`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <span className="font-bold text-slate-850 font-mono mt-1 block">{percentage}%</span>
                    </div>
                  ))}
                </div>

                {validationReport.distribution.some((p: number) => p > 55) && (
                  <div className="text-[11px] text-amber-700 flex gap-1 items-start bg-amber-50 rounded-xl p-2.5 mt-2 border border-amber-100">
                    <AlertTriangle size={12} className="shrink-0 mt-0.5 text-amber-600" />
                    <span>Внимание! Заметен перекос правильных ответов в сторону одного индекса. Рекомендуем перемешать списки при деплое.</span>
                  </div>
                )}
              </div>

              {/* Warning Log Outputs */}
              {validationReport.warnings.length > 0 ? (
                <div className="space-y-2">
                  <span className="text-[10px] text-slate-400 font-mono font-bold tracking-wider block">НАЙДЕННЫЕ ЗАМЕЧАНИЯ:</span>
                  <div className="max-h-48 overflow-y-auto space-y-2 divide-y divide-slate-100">
                    {validationReport.warnings.map((warn: string, idx: number) => (
                      <div key={idx} className="text-[11px] text-slate-600 pt-1.5 flex gap-2 items-start font-sans leading-relaxed">
                        <span className="font-bold text-amber-600 font-mono shrink-0">[!]</span>
                        <p>{warn}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-center py-4 bg-emerald-50/20 text-emerald-700 text-xs font-medium rounded-xl border border-emerald-100 flex items-center justify-center gap-1.5">
                  <CheckCircle2 size={16} />
                  <span>Поздравляем! Ошибок лимитирования символов и дубликатов в данном файле не обнаружено!</span>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-slate-50 border border-dashed border-slate-205 py-12 rounded-2xl text-center text-slate-400 text-xs">
              Запустите валидатор, чтобы получить подробный отчет проверки синтаксиса и качества
            </div>
          )}
        </div>

        {/* Main Deployment Actions Panel */}
        <div className="lg:col-span-2 lg:order-1 space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
            <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
              <Settings2 size={16} className="text-indigo-600" />
              Блок А: Загрузка квиза в Telegram
            </h3>

            <div className="space-y-1 text-xs">
              <label className="text-slate-400 block font-mono">ГРУППА ДЛЯ ЗАГРУЗКИ:</label>
              <div className="relative">
                <select
                  value={selectedGroupId}
                  onChange={(e) => {
                    setSelectedGroupId(e.target.value);
                    setValidationReport(null);
                  }}
                  disabled={isLocked}
                  className="appearance-none w-full font-bold text-slate-800 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 pr-10 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
                >
                  {quizGroups.map(g => (
                    <option key={g.id} value={g.id}>{g.name} ({g.questions.length} вопр.)</option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              </div>
            </div>

            {/* Custom BOT Title setting */}
            <div className="space-y-1 text-xs">
              <label className="text-slate-400 block font-mono">НАЗВАНИЕ КВИЗА В БОТЕ:</label>
              <input
                type="text"
                value={botTitle}
                onChange={(e) => setBotTitle(e.target.value)}
                disabled={isLocked}
                className="w-full text-slate-800 p-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {/* Upload Speed Selectors */}
            <div className="space-y-1.5 text-xs">
              <label className="text-slate-400 block font-mono flex items-center gap-1">
                <Gauge size={12} className="text-indigo-500" />
                СКОРОСТЬ ЗАГРУЗКИ:
              </label>
              <div className="grid grid-cols-2 gap-2 text-center select-none font-bold">
                <button
                  onClick={() => setUploadSpeed('normal')}
                  disabled={isLocked}
                  className={`p-2 rounded-xl text-[10px] font-bold border transition ${
                    uploadSpeed === 'normal'
                      ? 'bg-indigo-50 border-indigo-200 text-indigo-700'
                      : 'border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300'
                  }`}
                >
                  Обычная (Безопасная)
                </button>
                <button
                  onClick={() => setUploadSpeed('fast')}
                  disabled={isLocked}
                  className={`p-2 rounded-xl text-[10px] font-bold border transition ${
                    uploadSpeed === 'fast'
                      ? 'bg-indigo-50 border-indigo-200 text-indigo-700'
                      : 'border-slate-200 text-slate-500 hover:text-slate-700 hover:border-slate-300'
                  }`}
                >
                  Быстрая (Демо)
                </button>
              </div>
            </div>

            {/* Context type */}
            <div className="space-y-1 text-xs">
              <label className="text-slate-400 block font-mono">ОТПРАВКА КОНТЕКСТА:</label>
              <div className="relative">
                <select
                  value={contextMode}
                  onChange={(e: any) => setContextMode(e.target.value)}
                  disabled={isLocked}
                  className="appearance-none w-full text-slate-800 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-xs"
                >
                  <option value="once">Один раз для блока (Once)</option>
                  <option value="per_question">Каждому вопросу (Per-question)</option>
                </select>
                <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              </div>
            </div>

            {/* Shuffle options checkbox */}
            <label className="flex items-center gap-2 cursor-pointer select-none text-xs text-slate-600">
              <input
                type="checkbox"
                checked={shuffleOptions}
                onChange={(e) => setShuffleOptions(e.target.checked)}
                disabled={isLocked}
                className="rounded text-indigo-600 focus:ring-indigo-500 border-slate-300"
              />
              <span className="font-semibold">Перемешивать варианты ответов</span>
            </label>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-bold text-slate-900">Очередь отправки в Telegram</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Сначала набери несколько квизов, потом запусти очередь. Backend отправит их по одному.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={handleAddToTelegramQueue}
                    disabled={isLocked || !canDeploy || activeQueued}
                    className="px-3 py-2 rounded-lg bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 text-indigo-700 font-bold text-xs"
                  >
                    {activeQueued ? 'Уже в очереди' : 'В очередь'}
                  </button>
                  <button
                    onClick={handleAddAllToTelegramQueue}
                    disabled={isLocked || quizGroups.length === 0}
                    className="px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-700 font-bold text-xs"
                  >
                    Добавить все
                  </button>
                  <button
                    onClick={() => setTelegramQueue([])}
                    disabled={isLocked || telegramQueue.length === 0}
                    className="px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-500 font-bold text-xs"
                  >
                    Очистить
                  </button>
                </div>
              </div>

              {telegramQueue.length > 0 ? (
                <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100 max-h-52 overflow-y-auto">
                  {telegramQueue.map((item, index) => (
                    <div key={item.groupId} className="px-3 py-2 flex items-center justify-between gap-3 text-xs">
                      <div className="min-w-0">
                        <span className="font-mono font-bold text-indigo-600 mr-2">#{index + 1}</span>
                        <span className="font-bold text-slate-800">{item.name}</span>
                        <span className="text-slate-500 ml-2">({item.questions} вопр.)</span>
                      </div>
                      <button
                        onClick={() => handleRemoveFromTelegramQueue(item.groupId)}
                        disabled={isLocked}
                        className="text-slate-400 hover:text-rose-600 font-bold shrink-0"
                      >
                        Убрать
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-5 text-center text-xs text-slate-400">
                  Очередь пустая. Выбери группу выше и нажми "В очередь".
                </div>
              )}
            </div>

            {/* Launch Action */}
            <button
              onClick={handleDeployToTelegram}
              disabled={isLocked || !canDeploy}
              className={`w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 hover:shadow-lg hover:shadow-indigo-600/10 text-white font-bold text-xs rounded-xl transition flex items-center justify-center gap-2 ${
                isLocked || !canDeploy ? 'opacity-50 cursor-not-allowed bg-slate-200 text-slate-400 hover:shadow-none' : ''
              }`}
            >
              <SendToBack size={14} />
              <span>Отправить только выбранный</span>
            </button>
            <button
              onClick={handleStartTelegramQueue}
              disabled={isLocked || telegramQueue.length === 0}
              className={`w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-700 hover:shadow-lg hover:shadow-emerald-600/10 text-white font-bold text-xs rounded-xl transition flex items-center justify-center gap-2 ${
                isLocked || telegramQueue.length === 0 ? 'opacity-50 cursor-not-allowed bg-slate-200 text-slate-400 hover:shadow-none' : ''
              }`}
            >
              <Play size={14} />
              <span>Запустить очередь ({telegramQueue.length})</span>
            </button>
          </div>
        </div>

      </div>

      {/* Deployment Simulation Outputs Block */}
      {uploadCompleted && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4 animate-scaleUp">
          <div className="flex items-center gap-2 text-emerald-600 font-semibold text-sm">
            <CheckCircle2 size={18} />
            Загрузка успешно завешена! Квиз-группа развернута на сервере @QuizBot.
          </div>

          <div className="bg-slate-50 border border-slate-200 rounded-2xl p-5 flex flex-col sm:flex-row justify-between items-center gap-4">
            <div className="space-y-1 text-xs">
              <p className="font-bold text-slate-800">Квиз успешно импортирован на удаленный сервер Telegram</p>
              <p className="text-slate-500">Пользователи могут запустить его, перейдя по официальной ссылке-токену.</p>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleCopyLink}
                className="px-4 py-2 border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-semibold text-xs rounded-xl transition flex items-center gap-1.5"
              >
                <Copy size={13} />
                <span>{copied ? 'Скопировано!' : 'Скопировать ссылку'}</span>
              </button>

              <a
                href="https://t.me/QuizBot?start=historical_kaz_studio_quiz_f58b"
                target="_blank"
                rel="noreferrer"
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold text-xs rounded-xl transition flex items-center gap-1.5"
              >
                <span>Перейти в Telegram</span>
                <ExternalLink size={13} />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* Local manual advice banner Footer */}
      <div className="bg-slate-100 border border-slate-200 rounded-2xl p-5 flex gap-4 text-xs text-slate-600">
        <HelpCircle size={18} className="translate-y-0.5 shrink-0 text-slate-400" />
        <div className="space-y-1">
          <p className="font-semibold text-slate-800 font-sans">Стабильность соединения при импортах</p>
          <p className="leading-relaxed">Скрипт <code className="bg-white/80 border border-slate-200/50 rounded px-1">main.py</code> автоматизирует вызовы и удерживает пазы в 20 секунд (для снижения флуд-рейтингов Telegram API), загружая медиафайлы. Если Вы запустили Быстрый (Демо) режим, таймаут составит 5 секунд, будьте бдительны к лимитам.</p>
        </div>
      </div>
    </div>
  );
}
