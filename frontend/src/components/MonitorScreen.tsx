import { useEffect, useRef } from 'react';
import { 
  Square, 
  Terminal, 
  CircleDot,
} from 'lucide-react';
import { PipelineState, TaskStatus } from '../types';

interface MonitorScreenProps {
  pipeline: PipelineState;
  cancelPipeline: () => void;
  setActiveTab: (tab: string) => void;
  onGenerateAllGroups: () => Promise<void>;
}

export default function MonitorScreen({ pipeline, cancelPipeline, setActiveTab, onGenerateAllGroups }: MonitorScreenProps) {
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Auto scroll terminal logs
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [pipeline.logs]);

  const isRunning = pipeline.status !== 'idle';
  const result = pipeline.result || {};
  const report = result.report as Record<string, any> | undefined;
  const parsedGroups = Array.isArray(result.groups)
    ? (result.groups as unknown[]).filter((item): item is string => typeof item === 'string')
    : [];
  const generatedGroups = Array.isArray(result.groups)
    ? (result.groups as unknown[]).filter((item): item is Record<string, any> => typeof item === 'object' && item !== null)
    : [];
  const failures = Array.isArray(result.failures) ? result.failures as Array<Record<string, any>> : [];
  const skipped = Array.isArray(result.skipped) ? result.skipped as Array<Record<string, any>> : [];
  const queueItems = Array.isArray(result.queue) ? result.queue as Array<Record<string, any>> : [];
  const isGenerationResult = Boolean(result.output_dir);
  const hasParseResult = !isRunning && Boolean(result.source_path || report?.items_total || parsedGroups.length);
  const hasGenerateResult = Boolean(result.output_dir || generatedGroups.length || failures.length || queueItems.length);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div>
          <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Экран 2: Мониторинг задач (Pipeline Monitor)</h2>
          <p className="text-slate-500 text-sm mt-1">
            Отслеживание фоновых консольных задач, логов GPT-нормализации и безопасности параллельного выполнения.
          </p>
        </div>
      </div>

      <div className="space-y-6">
          
          {/* Progress Card */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
                <span className="w-1.5 h-3 bg-indigo-600 rounded-full" />
                Текущая задача: {pipeline.status === 'idle' ? 'Ожидание запуска...' : pipeline.status === 'parsing' ? 'Распаковка DOCX-документа' : pipeline.status === 'normalizing' ? 'Нормализация вопросов через GPT API' : 'Загрузка вопросов в Telegram-бот'}
              </h3>
              {isRunning && (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono px-2 py-1 rounded bg-indigo-50 text-indigo-700 border border-indigo-100 font-bold animate-pulse">
                    {pipeline.status.toUpperCase()}
                  </span>
                  <button
                    type="button"
                    onClick={cancelPipeline}
                    className="px-3 py-2 bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs rounded-xl transition flex items-center justify-center gap-2 shadow-sm shadow-rose-600/10"
                  >
                    <Square size={13} />
                    Остановить
                  </button>
                </div>
              )}
            </div>

            {isRunning ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs text-slate-500 font-mono">
                  <span className="truncate max-w-xs sm:max-w-md">Статус: {pipeline.currentStep}</span>
                  <span>{pipeline.progress}%</span>
                </div>
                
                {/* Visual Progress Bar */}
                <div className="w-full bg-slate-100 h-3 rounded-full overflow-hidden border border-slate-200/50">
                  <div 
                    className="bg-indigo-600 h-full rounded-full transition-all duration-300"
                    style={{ width: `${pipeline.progress}%` }}
                  />
                </div>

                <div className="flex justify-between items-center pt-1 text-xs text-slate-400">
                  <span>Обработка квиза: <strong>{pipeline.currentGroup}</strong></span>
                  <span>Осталось примерно: <strong className="font-mono text-slate-700">{pipeline.eta} сек (ETA)</strong></span>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-slate-400 flex flex-col items-center justify-center">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-350 flex items-center justify-center mb-2">
                  <CircleDot size={20} className="animate-pulse" />
                </div>
                <p className="font-semibold text-sm text-slate-600">Нет активных процессов</p>
                <p className="text-xs text-slate-400 max-w-sm mt-0.5">Перейдите во вкладки "Импорт" или "Валидация", чтобы инициировать парсинг или Telegram деплоймент.</p>
              </div>
            )}
          </div>

          {/* Real job result summary */}
          {(hasParseResult || hasGenerateResult || (!isRunning && result.report)) && (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-5">
              <div>
                <h3 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
                  <span className="w-1.5 h-3 bg-emerald-600 rounded-full" />
                  Результат последней задачи
                </h3>
                <p className="text-xs text-slate-500 mt-1">
                  Это реальный результат backend job. Дальше выбирай следующий шаг, не возвращаясь вручную по вкладкам.
                </p>
              </div>

              {report && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {Object.entries({
                    blocks_total: report.blocks_total,
                    items_total: report.items_total ?? report.questions_total,
                    items_with_media: report.items_with_media ?? report.media_count,
                    items_needs_review: report.items_needs_review ?? report.warnings?.length,
                  }).map(([key, value]) => (
                    <div key={key} className="p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <span className="text-[10px] text-slate-400 font-mono block uppercase">{key}</span>
                      <span className="text-lg font-bold text-slate-800 font-mono">{value ?? 0}</span>
                    </div>
                  ))}
                </div>
              )}

              {parsedGroups.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] text-slate-400 font-mono font-bold tracking-wider block">НАЙДЕННЫЕ ГРУППЫ В DOCX:</span>
                  <div className="max-h-40 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100 bg-slate-50">
                    {parsedGroups.map((line, index) => (
                      <div key={index} className="px-3 py-2 text-xs text-slate-700 font-mono">
                        {line}
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={onGenerateAllGroups}
                    className="w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl transition flex items-center justify-center gap-2"
                  >
                    Создать готовые JSON по всем группам
                  </button>
                </div>
              )}

              {hasGenerateResult && (
                <div className="space-y-3">
                  {queueItems.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-[10px] text-slate-400 font-mono font-bold tracking-wider block">ОЧЕРЕДЬ ЗАДАЧ:</span>
                      <div className="max-h-52 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100 bg-white">
                        {queueItems.map((item, index) => {
                          const status = String(item.status || 'queued');
                          const badge =
                            status === 'ready'
                              ? 'bg-emerald-100 text-emerald-800'
                              : status === 'creating'
                                ? 'bg-indigo-100 text-indigo-800'
                                : status === 'error'
                                  ? 'bg-rose-100 text-rose-800'
                                  : status === 'cancelled'
                                    ? 'bg-slate-200 text-slate-600'
                                    : 'bg-slate-100 text-slate-600';
                          return (
                            <div key={`${String(item.group || '')}-${index}`} className="px-3 py-2 text-xs flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <span className="font-mono font-bold text-slate-400 mr-2">#{index + 1}</span>
                                <span className="font-bold text-slate-800">{String(item.group || '')}</span>
                                <span className="text-slate-400 ml-2">({Number(item.questions || 0)} вопр.)</span>
                              </div>
                              <span className={`px-2 py-1 rounded-full font-bold shrink-0 ${badge}`}>{status}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <span className="text-[10px] text-slate-400 font-mono font-bold tracking-wider block">{isGenerationResult ? 'СОЗДАННЫЕ JSON:' : 'РЕЗУЛЬТАТЫ ОТПРАВКИ:'}</span>
                  <div className="max-h-40 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100 bg-slate-50">
                    {generatedGroups.map((item, index) => (
                      <div key={index} className="px-3 py-2 text-xs text-slate-700">
                        <span className="font-bold">{String(item.group || '')}</span>
                        <span className="text-slate-400"> — {String(item.output || item.group_id || '')}</span>
                      </div>
                    ))}
                    {skipped.map((item, index) => (
                      <div key={`skip-${index}`} className="px-3 py-2 text-xs text-emerald-700">
                        Уже готово: {String(item.group || '')} <span className="text-slate-400">— {String(item.output || '')}</span>
                      </div>
                    ))}
                    {failures.map((item, index) => (
                      <div key={`fail-${index}`} className="px-3 py-2 text-xs text-rose-700">
                        Ошибка: {String(item.group || '')} {String(item.error || item.exit_code || '')}
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => setActiveTab('editor')}
                    className="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl transition"
                  >
                    Перейти в редактор групп
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Terminal / Live Logs View */}
          <div className="bg-slate-950 rounded-2xl border border-slate-800 shadow-xl overflow-hidden flex flex-col min-h-[320px] h-[46vh] max-h-[520px]">
            {/* Terminal Tab Bar */}
            <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 flex items-center justify-between shrink-0 font-mono text-xs text-slate-500 select-none">
              <div className="flex items-center gap-2">
                <Terminal size={14} className="text-slate-400" />
                <span className="text-slate-300">Логи процесса (Live Logs)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/80" />
                <span className="w-2.5 h-2.5 rounded-full bg-green-500/80" />
              </div>
            </div>

            {/* Terminal Body */}
            <div 
              ref={logContainerRef}
              className="flex-1 p-5 font-mono text-xs overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-slate-800"
            >
              {pipeline.logs.length === 0 ? (
                <div className="text-slate-600 italic select-none">Терминал готов к выводу логов команд...</div>
              ) : (
                pipeline.logs.map((log, index) => {
                  let color = 'text-slate-300';
                  if (log.type === 'success') color = 'text-emerald-400';
                  if (log.type === 'warn') color = 'text-amber-400 font-semibold';
                  if (log.type === 'error') color = 'text-rose-500 font-bold';
                  if (log.type === 'terminal') color = 'text-indigo-400';

                  return (
                    <div key={index} className="flex gap-2 items-start leading-relaxed hover:bg-slate-900/40 p-0.5 rounded">
                      <span className="text-slate-600 select-none shrink-0 font-light">{log.time}</span>
                      <span className={`${color} break-all whitespace-pre-wrap flex-1`}>{log.message}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
      </div>
    </div>
  );
}
