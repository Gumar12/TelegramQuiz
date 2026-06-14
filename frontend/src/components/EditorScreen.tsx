import React, { useState, useEffect } from 'react';
import { 
  ChevronDown, 
  Plus, 
  Trash2, 
  Sparkles, 
  Download, 
  HelpCircle, 
  Save, 
  AlertCircle, 
  FileCheck, 
  Undo,
  CornerDownRight,
  Eye,
  CheckCircle2,
  Image as ImageIcon,
  Loader2,
  Maximize2,
  UploadCloud,
  X
} from 'lucide-react';
import { QuizGroup, Question, SourceGroupSummary, TaskStatus } from '../types';
import { validateQuestion } from '../utils/similarity';
import { mediaUrl } from '../api';

interface EditorScreenProps {
  status: TaskStatus;
  quizGroups: QuizGroup[];
  sourceGroups?: SourceGroupSummary[];
  generationQueue?: SourceGroupSummary[];
  onGenerateAllGroups?: () => void | Promise<void>;
  queueGroupForGeneration?: (group: SourceGroupSummary) => void;
  queueAllMissingGroups?: () => void;
  removeQueuedGroup?: (groupName: string) => void;
  clearGenerationQueue?: () => void;
  startGenerationQueue?: () => void | Promise<void>;
  uploadMedia: (file: File) => Promise<string>;
  updateQuizGroup: (groupId: string, updatedGroup: QuizGroup) => void | Promise<void>;
}

export default function EditorScreen({
  status,
  quizGroups,
  sourceGroups = [],
  generationQueue = [],
  onGenerateAllGroups,
  queueGroupForGeneration,
  queueAllMissingGroups,
  removeQueuedGroup,
  clearGenerationQueue,
  startGenerationQueue,
  uploadMedia,
  updateQuizGroup,
}: EditorScreenProps) {
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [removedQuestions, setRemovedQuestions] = useState<{ q: Question; index: number }[]>([]);
  const [saveToast, setSaveToast] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [saveToastMessage, setSaveToastMessage] = useState('');
  const [aiEnhancingIndex, setAiEnhancingIndex] = useState<number | null>(null);
  const [uploadingMediaIndex, setUploadingMediaIndex] = useState<number | null>(null);
  const [contextModal, setContextModal] = useState<{ index: number; text: string } | null>(null);

  // Initialize group
  useEffect(() => {
    if (quizGroups.length > 0 && !selectedGroupId) {
      setSelectedGroupId(quizGroups[0].id);
    }
  }, [quizGroups]);

  const currentGroup = quizGroups.find(g => g.id === selectedGroupId);
  const missingSourceGroups = sourceGroups.filter(
    (sourceGroup) => !sourceGroup.generated && !quizGroups.some((group) => group.id === sourceGroup.id)
  );
  const sourceQuestionsTotal = sourceGroups.reduce((sum, group) => sum + group.questions_count, 0);
  const queuedNames = new Set(generationQueue.map((group) => group.name));

  const mediaFileName = (path: string) => path.replace(/\\/g, '/').split('/').pop() || path;

  useEffect(() => {
    if (currentGroup) {
      setQuestions(JSON.parse(JSON.stringify(currentGroup.questions))); // deep clone
      setRemovedQuestions([]);
    }
  }, [selectedGroupId, quizGroups]);

  const isLocked = status !== 'idle';

  // Handle value modifications
  const handleModifyQuestion = (index: number, field: keyof Question, value: any) => {
    const next = [...questions];
    next[index] = { ...next[index], [field]: value };
    setQuestions(next);
  };

  const handleModifyOption = (qIndex: number, optIndex: number, text: string) => {
    const next = [...questions];
    const nextOptions = [...next[qIndex].options];
    nextOptions[optIndex] = text;
    next[qIndex] = { ...next[qIndex], options: nextOptions };
    setQuestions(next);
  };

  const handleAddOption = (qIndex: number) => {
    const next = [...questions];
    if (next[qIndex].options.length >= 10) return;
    next[qIndex].options = [...next[qIndex].options, `Новый вариант ответов ${next[qIndex].options.length + 1}`];
    setQuestions(next);
  };

  const handleRemoveOption = (qIndex: number, optIndex: number) => {
    const next = [...questions];
    if (next[qIndex].options.length <= 2) return;
    const nextOptions = next[qIndex].options.filter((_, idx) => idx !== optIndex);
    next[qIndex] = { ...next[qIndex], options: nextOptions };
    
    // Adjust correct answers boundary if it was out of bounds
    if (next[qIndex].correct >= nextOptions.length) {
      next[qIndex].correct = 0;
    }
    setQuestions(next);
  };

  const handleUploadMedia = async (qIndex: number, file: File | null | undefined) => {
    if (!file || isLocked) return;
    setUploadingMediaIndex(qIndex);
    try {
      const uploadedPath = await uploadMedia(file);
      const next = [...questions];
      const currentMedia = Array.isArray(next[qIndex].media) ? next[qIndex].media : [];
      next[qIndex] = {
        ...next[qIndex],
        media: [...currentMedia, uploadedPath],
      };
      setQuestions(next);
    } catch (error) {
      setSaveToast('error');
      setSaveToastMessage(error instanceof Error ? error.message : 'Не удалось загрузить фото');
      window.setTimeout(() => setSaveToast('idle'), 4500);
    } finally {
      setUploadingMediaIndex(null);
    }
  };

  const handleRemoveMedia = (qIndex: number, mediaIndex: number) => {
    const next = [...questions];
    const currentMedia = Array.isArray(next[qIndex].media) ? next[qIndex].media : [];
    next[qIndex] = {
      ...next[qIndex],
      media: currentMedia.filter((_, index) => index !== mediaIndex),
    };
    setQuestions(next);
  };

  const openContextModal = (qIndex: number) => {
    setContextModal({ index: qIndex, text: questions[qIndex]?.context || '' });
  };

  const saveContextModal = () => {
    if (!contextModal) return;
    handleModifyQuestion(contextModal.index, 'context', contextModal.text);
    setContextModal(null);
  };

  const handleAddQuestion = () => {
    const newQ: Question = {
      id: `q_new_${Date.now()}`,
      question: 'Введите текст нового вопроса?',
      options: ['Вариант A', 'Вариант B', 'Вариант C', 'Вариант D'],
      correct: 0,
      explanation: 'Введите объяснение для закрепления материала.'
    };
    setQuestions([...questions, newQ]);
  };

  const handleRemoveQuestion = (qIndex: number) => {
    const qToRemove = questions[qIndex];
    setRemovedQuestions([...removedQuestions, { q: qToRemove, index: qIndex }]);
    setQuestions(questions.filter((_, idx) => idx !== qIndex));
  };

  const handleUndoRemove = () => {
    if (removedQuestions.length === 0) return;
    const lastRemoved = removedQuestions[removedQuestions.length - 1];
    
    const nextQuestions = [...questions];
    nextQuestions.splice(lastRemoved.index, 0, lastRemoved.q);
    setQuestions(nextQuestions);
    setRemovedQuestions(removedQuestions.slice(0, -1));
  };

  const handleSaveGroup = async () => {
    if (!currentGroup || saveToast === 'saving') return;
    
    // Determine overall status based on warnings
    let warningCount = 0;
    questions.forEach(q => {
      const pWarns = validateQuestion(q.question, q.options, q.correct, q.explanation);
      if (pWarns.length > 0) warningCount += pWarns.length;
    });

    const updatedGroup: QuizGroup = {
      ...currentGroup,
      questions,
      status: warningCount > 0 ? 'review' : 'ready'
    };

    setSaveToast('saving');
    setSaveToastMessage('Сохранение изменений...');
    try {
      await updateQuizGroup(selectedGroupId, updatedGroup);
      setSaveToast('saved');
      setSaveToastMessage('Сохранилось');
      window.setTimeout(() => setSaveToast('idle'), 2500);
    } catch (error) {
      setSaveToast('error');
      setSaveToastMessage(error instanceof Error ? error.message : 'Не удалось сохранить');
      window.setTimeout(() => setSaveToast('idle'), 4500);
    }
  };

  // Simulated AI enhancer
  const handleAiEnhanceExplanation = (qIndex: number) => {
    if (isLocked) return;
    setAiEnhancingIndex(qIndex);
    
    setTimeout(() => {
      const q = questions[qIndex];
      let prefix = 'Краткая историческая справка: ';
      if (q.question.toLowerCase().includes('аблай') || q.question.toLowerCase().includes('абылай')) {
        prefix = 'Абылай-хан провел важные реформы, укрепившие боеспособность ополчения всех жузов.';
      } else if (q.question.toLowerCase().includes('закон') || q.question.toLowerCase().includes('жаргы')) {
        prefix = 'Свод «Жеты Жаргы» опирался на традиционные установления кочевников и прекратил усобицы в жузах.';
      } else if (q.question.toLowerCase().includes('битва') || q.question.toLowerCase().includes('анракай')) {
        prefix = 'Анракайское сражение стало знаковым триумфом народного духа, объединившим ополчения трех жузов.';
      } else {
        prefix = `Данный факт подтверждается архивными источниками по истории Казахстана.`;
      }

      const enhanced = `${prefix} Текст полностью адаптирован под лимиты Telegram-сообщений.`;
      handleModifyQuestion(qIndex, 'explanation', enhanced.substring(0, 200));
      setAiEnhancingIndex(null);
    }, 1500);
  };

  // Action: Raw JSON Download
  const handleDownloadJson = () => {
    if (!currentGroup) return;
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(questions, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `${currentGroup.id}_quizzes.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  if (quizGroups.length === 0 && sourceGroups.length > 0) {
    return (
      <div className="bg-white rounded-lg border border-slate-200 p-8 text-center text-slate-500 space-y-4">
        <p>
          {`DOCX разобран: найдено ${sourceGroups.length} групп и ${sourceQuestionsTotal} вопросов, но готовые JSON еще не созданы.`}
        </p>
        {(queueAllMissingGroups || onGenerateAllGroups) && (
          <button
            onClick={queueAllMissingGroups || onGenerateAllGroups}
            disabled={isLocked}
            className="mx-auto px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-bold text-xs rounded-lg transition flex items-center gap-2"
          >
            <FileCheck size={14} />
            <span>Добавить все неготовые в очередь</span>
          </button>
        )}
        {startGenerationQueue && generationQueue.length > 0 && (
          <button
            onClick={startGenerationQueue}
            disabled={isLocked}
            className="mx-auto px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white font-bold text-xs rounded-lg transition"
          >
            Запустить очередь ({generationQueue.length})
          </button>
        )}
      </div>
    );
  }

  if (quizGroups.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center text-slate-500">
        Нет доступных групп для редактирования. Сначала импортируйте DOCX файл в Шаге 1.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Upper header action blocks */}
      <div className="flex md:flex-row flex-col justify-between md:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Экран 3: Визуальный редактор квизов (JSON Editor)</h2>
          <p className="text-slate-500 text-sm mt-1">
            Гибкое управление наполнением групп. Правим JSON файлы «на лету» без участия программистов.
          </p>
        </div>

        <div className="flex gap-2 items-center">
          <button
            onClick={handleDownloadJson}
            disabled={!currentGroup}
            className="px-4 py-2 border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-semibold text-xs rounded-xl transition flex items-center gap-2"
          >
            <Download size={14} />
            <span>Скачать JSON группы</span>
          </button>
        </div>
      </div>

      {sourceGroups.length > quizGroups.length && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertCircle size={18} className="text-amber-700 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-bold text-amber-900">Не все группы превращены в готовые JSON</h3>
              <p className="text-xs text-amber-800 mt-1 leading-relaxed">
                В исходнике найдено {sourceGroups.length} групп / {sourceQuestionsTotal} вопросов. В редакторе сейчас доступны только файлы из папки quizzes: {quizGroups.length}.
              </p>
              {missingSourceGroups.length > 0 && (
                <p className="text-xs text-amber-700 mt-2">
                  Не готовы: {missingSourceGroups.slice(0, 8).map((group) => `${group.name} (${group.questions_count})`).join(', ')}
                  {missingSourceGroups.length > 8 ? ` и еще ${missingSourceGroups.length - 8}` : ''}.
                </p>
              )}
            </div>
          </div>
          {(queueAllMissingGroups || onGenerateAllGroups) && (
            <button
              onClick={queueAllMissingGroups || onGenerateAllGroups}
              disabled={isLocked}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-bold text-xs rounded-lg transition flex items-center gap-2 shrink-0"
            >
              <FileCheck size={14} />
              <span>Добавить все неготовые в очередь</span>
            </button>
          )}
        </div>
      )}

      {(missingSourceGroups.length > 0 || generationQueue.length > 0) && (
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-slate-900">Очередь создания JSON</h3>
              <p className="text-xs text-slate-500 mt-1">
                Добавь нужные группы в очередь. Backend создаст их строго по порядку: первая, потом вторая, потом третья.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {queueAllMissingGroups && (
                <button
                  onClick={queueAllMissingGroups}
                  disabled={isLocked || missingSourceGroups.length === 0}
                  className="px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 disabled:opacity-50 text-slate-700 font-bold text-xs"
                >
                  Добавить все
                </button>
              )}
              {clearGenerationQueue && (
                <button
                  onClick={clearGenerationQueue}
                  disabled={isLocked || generationQueue.length === 0}
                  className="px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 text-slate-600 font-bold text-xs"
                >
                  Очистить
                </button>
              )}
              {startGenerationQueue && (
                <button
                  onClick={startGenerationQueue}
                  disabled={isLocked || generationQueue.length === 0}
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white font-bold text-xs"
                >
                  Запустить очередь ({generationQueue.length})
                </button>
              )}
            </div>
          </div>

          {generationQueue.length > 0 && (
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 divide-y divide-emerald-100">
              {generationQueue.map((group, index) => (
                <div key={group.name} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                  <div className="min-w-0">
                    <span className="font-mono font-bold text-emerald-700 mr-2">#{index + 1}</span>
                    <span className="font-bold text-slate-800">{group.name}</span>
                    <span className="text-slate-500 ml-2">({group.questions_count} вопр.)</span>
                  </div>
                  {removeQueuedGroup && (
                    <button
                      onClick={() => removeQueuedGroup(group.name)}
                      disabled={isLocked}
                      className="text-slate-400 hover:text-rose-600 font-bold shrink-0"
                    >
                      Убрать
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {missingSourceGroups.length > 0 && (
            <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-200 divide-y divide-slate-100">
              {missingSourceGroups.map((group) => {
                const queued = queuedNames.has(group.name);
                return (
                  <div key={group.name} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                    <div className="min-w-0">
                      <span className="font-bold text-slate-800">{group.name}</span>
                      <span className="text-slate-500 ml-2">({group.questions_count} вопр.)</span>
                    </div>
                    <button
                      onClick={() => queueGroupForGeneration?.(group)}
                      disabled={isLocked || queued || !queueGroupForGeneration}
                      className={`px-3 py-1.5 rounded-lg font-bold shrink-0 ${
                        queued
                          ? 'bg-emerald-100 text-emerald-700'
                          : 'bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                      }`}
                    >
                      {queued ? 'В очереди' : 'В очередь'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Select active group panel */}
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-400 font-mono tracking-wider font-bold">ВЫБОР КВИЗ-ГРУППЫ:</label>
          <div className="relative">
            <select
              value={selectedGroupId}
              onChange={(e) => setSelectedGroupId(e.target.value)}
              disabled={isLocked}
              className="appearance-none font-semibold text-slate-800 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2 pr-10 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer"
            >
              {quizGroups.map(g => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.questions.length} вопр.)
                </option>
              ))}
              {missingSourceGroups.map(g => (
                <option key={g.id} value={g.id} disabled>
                  {g.name} ({g.questions_count} вопр.) - JSON еще не создан
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          </div>
        </div>

        {currentGroup && (
          <div className="flex items-center gap-3 text-xs">
            <span className="text-slate-400">Статус:</span>
            {currentGroup.status === 'ready' ? (
              <span className="px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800 font-bold flex items-center gap-1.5 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> GOT-READY
              </span>
            ) : currentGroup.status === 'review' ? (
              <span className="px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 font-bold flex items-center gap-1.5 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> NEEDS-REVIEW
              </span>
            ) : (
              <span className="px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 font-bold flex items-center gap-1.5 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-400" /> SAVED DRAFT
              </span>
            )}

            <span className="text-slate-450">| Категория: {currentGroup.description}</span>
          </div>
        )}
      </div>

      {/* Trash undo actions alert */}
      {removedQuestions.length > 0 && (
        <div className="bg-slate-900 text-white px-4 py-3 rounded-2xl flex items-center justify-between shadow-lg text-xs animate-slideDown">
          <div className="flex items-center gap-2">
            <Trash2 size={14} className="text-red-400" />
            <span>Вопрос перемещен во временную корзину. Вы можете вернуть его до сохранения изменений.</span>
          </div>
          <button 
            onClick={handleUndoRemove} 
            className="text-indigo-400 hover:text-indigo-300 font-bold flex items-center gap-1.5 font-sans"
          >
            <Undo size={14} /> Отменить удаление
          </button>
        </div>
      )}

      {/* SAVE SUCCESS NOTIFICATION */}
      {false && (
        <div className="bg-emerald-600 text-white px-5 py-3 rounded-2xl flex items-center gap-2 shadow-lg text-xs animate-fadeIn font-semibold">
          <CheckCircle2 size={16} />
          Изменения успешно сохранены! Статус квизной группы обновлен.
        </div>
      )}

      {/* SAVE TOAST */}
      {saveToast !== 'idle' && (
        <div className={`fixed bottom-6 right-6 z-50 px-5 py-4 rounded-lg shadow-xl border text-sm font-semibold flex items-center gap-3 ${
          saveToast === 'error'
            ? 'bg-rose-600 text-white border-rose-500'
            : saveToast === 'saved'
              ? 'bg-emerald-600 text-white border-emerald-500'
              : 'bg-slate-900 text-white border-slate-700'
        }`}>
          {saveToast === 'saving' ? (
            <Loader2 size={17} className="animate-spin" />
          ) : saveToast === 'saved' ? (
            <CheckCircle2 size={17} />
          ) : (
            <AlertCircle size={17} />
          )}
          <span>{saveToastMessage}</span>
        </div>
      )}

      {contextModal && (
        <div className="fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-4xl bg-white rounded-2xl border border-slate-200 shadow-2xl overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Редактирование контекста</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Вопрос #{contextModal.index + 1}. Этот текст будет сохранен в поле context текущего вопроса.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setContextModal(null)}
                className="w-9 h-9 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-500 flex items-center justify-center shrink-0"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <textarea
                value={contextModal.text}
                onChange={(event) => setContextModal({ ...contextModal, text: event.target.value })}
                rows={18}
                autoFocus
                disabled={isLocked}
                className="w-full min-h-[420px] resize-y rounded-xl border border-slate-200 p-4 text-sm leading-relaxed text-slate-850 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="Вставьте или отредактируйте большой контекст здесь..."
              />
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <span className="text-xs text-slate-400 font-mono">{contextModal.text.length} симв.</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setContextModal(null)}
                    className="px-4 py-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-bold text-xs"
                  >
                    Отмена
                  </button>
                  <button
                    type="button"
                    onClick={saveContextModal}
                    disabled={isLocked}
                    className="px-5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-bold text-xs"
                  >
                    Сохранить контекст
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Questions List */}
      <div className="space-y-6">
        {questions.map((q, qIdx) => {
          // Dynamic warnings running similarity matching + limit thresholds
          const currentWarnings = validateQuestion(q.question, q.options, q.correct, q.explanation);
          const mediaItems = Array.isArray(q.media) ? q.media.filter(Boolean) : [];
          const hasBigErrors = currentWarnings.some(w => w.includes('Превышен лимит'));
          const hasSimilarWarning = currentWarnings.some(w => w.includes('Обнаружены схожие'));

          return (
            <div 
              key={q.id}
              className={`bg-white rounded-2xl border transition-all p-6 space-y-4 ${
                hasBigErrors 
                  ? 'border-rose-300 shadow-sm shadow-rose-50' 
                  : hasSimilarWarning 
                    ? 'border-amber-300 shadow-sm shadow-amber-50' 
                    : 'border-slate-200 hover:shadow-md'
              }`}
            >
              {/* Card Header controls */}
              <div className="flex items-center justify-between pb-3 border-b border-slate-100 select-none">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-lg bg-indigo-50 text-indigo-700 text-xs font-bold font-mono flex items-center justify-center">
                    {qIdx + 1}
                  </span>
                  <span className="text-xs font-semibold text-slate-500">Карточка вопроса</span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleAiEnhanceExplanation(qIdx)}
                    disabled={isLocked || aiEnhancingIndex === qIdx}
                    className="p-1 px-2.5 rounded-lg border border-indigo-150 bg-indigo-50/50 text-indigo-700 hover:bg-indigo-50 text-[10px] font-bold flex items-center gap-1 transition"
                  >
                    <Sparkles size={11} className={aiEnhancingIndex === qIdx ? 'animate-spin' : ''} />
                    <span>{aiEnhancingIndex === qIdx ? 'AI нормализация...' : 'ИИ-Улучшить объяснение'}</span>
                  </button>
                  
                  <button
                    onClick={() => handleRemoveQuestion(qIdx)}
                    className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition"
                    title="Удалить вопрос целиком"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Warnings List Panel */}
              {currentWarnings.length > 0 && (
                <div className="bg-amber-50/70 border border-amber-200.5 rounded-xl p-3 space-y-1">
                  <div className="flex items-center gap-1.5 text-[10px] font-bold text-amber-800 font-mono tracking-wider">
                    <AlertCircle size={12} className="shrink-0 text-amber-600" />
                    <span>НАЙДЕНЫ ОШИБКИ ВАЛИДАЦИИ TELEGRAM:</span>
                  </div>
                  <ul className="list-disc list-inside text-[11px] text-amber-700 space-y-0.5 ml-1">
                    {currentWarnings.map((warn, wIdx) => (
                      <li key={wIdx}>{warn}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Form Grid Elements */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
                {/* Context Field */}
                <div className="md:col-span-1 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-400 block font-mono">КОНТЕКСТ:</span>
                    <button
                      type="button"
                      onClick={() => openContextModal(qIdx)}
                      disabled={isLocked}
                      className="px-2 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 text-[10px] text-slate-600 font-bold flex items-center gap-1"
                    >
                      <Maximize2 size={11} />
                      <span>Открыть</span>
                    </button>
                  </div>
                  <textarea
                    value={q.context || ''}
                    onChange={(e) => handleModifyQuestion(qIdx, 'context', e.target.value)}
                    placeholder="Контекст, который будет отправлен перед вопросом"
                    disabled={isLocked}
                    rows={5}
                    className="w-full min-h-28 resize-y text-slate-850 p-2 border border-slate-205 rounded-xl bg-slate-55/40 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 leading-relaxed"
                  />

                  <div className="flex items-center justify-between gap-2 pt-1">
                    <span className="text-slate-400 block font-mono text-[10px]">МЕДИА:</span>
                    <label className={`px-2 py-1 rounded-lg border border-indigo-100 bg-indigo-50 hover:bg-indigo-100 text-[10px] text-indigo-700 font-bold flex items-center gap-1 cursor-pointer ${isLocked || uploadingMediaIndex === qIdx ? 'opacity-50 pointer-events-none' : ''}`}>
                      {uploadingMediaIndex === qIdx ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <UploadCloud size={11} />
                      )}
                      <span>{uploadingMediaIndex === qIdx ? 'Загрузка...' : 'Загрузить фото'}</span>
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        className="hidden"
                        disabled={isLocked || uploadingMediaIndex === qIdx}
                        onChange={(event) => {
                          const selectedFile = event.target.files?.[0];
                          void handleUploadMedia(qIdx, selectedFile);
                          event.target.value = '';
                        }}
                      />
                    </label>
                  </div>
                  {mediaItems.length > 0 ? (
                    <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 p-2 space-y-2">
                      <div className="text-[10px] text-indigo-800 font-bold flex items-center gap-1">
                        <ImageIcon size={11} className="text-indigo-600" />
                        <span>Фото прикреплено: {mediaItems.length}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {mediaItems.map((item, mediaIdx) => (
                          <div
                            key={`${item}_${mediaIdx}`}
                            className="group relative rounded-md border border-indigo-100 bg-white overflow-hidden hover:border-indigo-300"
                          >
                            <a href={mediaUrl(item)} target="_blank" rel="noreferrer" title={item}>
                              <img
                                src={mediaUrl(item)}
                                alt={`Фото контекста ${mediaIdx + 1}`}
                                className="w-full aspect-square object-cover bg-slate-100"
                              />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleRemoveMedia(qIdx, mediaIdx)}
                              disabled={isLocked}
                              className="absolute right-1 top-1 w-6 h-6 rounded-md bg-white/90 text-slate-500 hover:text-rose-600 hover:bg-white border border-slate-200 flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
                              title="Убрать фото из вопроса"
                            >
                              <X size={12} />
                            </button>
                            <span className="block px-1.5 py-1 text-[9px] text-slate-500 truncate group-hover:text-indigo-700">
                              {mediaFileName(item)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] text-slate-500 flex items-center gap-1">
                      <ImageIcon size={10} className="text-slate-400" />
                      <span>Фото не прикреплено</span>
                    </div>
                  )}
                </div>

                {/* Question text & Explanation field */}
                <div className="md:col-span-3 space-y-4">
                  {/* Main Question Text */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[11px]">
                      <span className="text-slate-400 font-mono">ТЕНДЕРНЫЙ ТЕКСТ ВОПРОСА (MAX 300):</span>
                      <span className={`font-mono font-semibold ${q.question.length > 300 ? 'text-rose-600' : 'text-slate-400'}`}>
                        {q.question.length} / 300 симв.
                      </span>
                    </div>
                    <textarea
                      value={q.question}
                      onChange={(e) => handleModifyQuestion(qIdx, 'question', e.target.value)}
                      rows={2}
                      disabled={isLocked}
                      className="w-full text-slate-850 p-2.5 border border-slate-205 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 font-sans"
                    />
                  </div>

                  {/* Dynamic Explanation block with char counter */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[11px]">
                      <span className="text-slate-400 font-mono">ОБЪЯСНЕНИЕ ОТВЕТА (MAX 200/ОБЯЗАТЕЛЬНО):</span>
                      <span className={`font-mono font-semibold ${(q.explanation || '').length > 200 ? 'text-rose-600' : 'text-slate-400'}`}>
                        {(q.explanation || '').length} / 200 симв.
                      </span>
                    </div>
                    <textarea
                      value={q.explanation || ''}
                      onChange={(e) => handleModifyQuestion(qIdx, 'explanation', e.target.value)}
                      rows={2}
                      disabled={isLocked}
                      placeholder="Например: Абылай хан признал дипломатическое..."
                      className="w-full text-slate-850 p-2.5 border border-slate-205 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 font-sans bg-emerald-50/5 text-slate-800"
                    />
                  </div>
                </div>
              </div>

              {/* Answers visual builder */}
              <div className="pt-2 space-y-2">
                <span className="text-[11px] text-slate-400 block font-mono">ВАРИАНТЫ ОТВЕТОВ (ОТ 2 ДО 10, КЛИКНИТЕ КРУГ ДЛЯ ВЫБОРА ПРАВИЛЬНОГО):</span>
                
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {q.options.map((option, optIdx) => {
                    const isCorrect = q.correct === optIdx;
                    return (
                      <div 
                        key={optIdx} 
                        className={`flex items-center gap-2.5 p-2 rounded-xl border transition-all ${
                          isCorrect 
                            ? 'border-emerald-300 bg-emerald-50/40 shadow-sm' 
                            : 'border-slate-150 hover:border-slate-300'
                        }`}
                      >
                        <input
                          type="radio"
                          name={`correct_${q.id}`}
                          checked={isCorrect}
                          onChange={() => handleModifyQuestion(qIdx, 'correct', optIdx)}
                          className="w-4 h-4 text-emerald-600 focus:ring-emerald-500 border-slate-300 cursor-pointer"
                        />
                        
                        <div className="flex-1 min-w-0 flex items-center gap-1">
                          <input
                            type="text"
                            value={option}
                            onChange={(e) => handleModifyOption(qIdx, optIdx, e.target.value)}
                            maxLength={110}
                            disabled={isLocked}
                            className={`w-full bg-transparent p-1 focus:outline-none text-xs text-slate-850 ${isCorrect ? 'font-semibold text-emerald-900' : ''}`}
                          />
                          <span className={`text-[9px] font-mono shrink-0 px-1.5 ${option.length > 100 ? 'text-rose-600 font-bold' : 'text-slate-400'}`}>
                            {option.length}/100
                          </span>
                        </div>

                        {q.options.length > 2 && (
                          <button
                            onClick={() => handleRemoveOption(qIdx, optIdx)}
                            disabled={isLocked}
                            className="text-slate-350 hover:text-rose-500 p-1 rounded-md"
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>

                {q.options.length < 10 && (
                  <button
                    onClick={() => handleAddOption(qIdx)}
                    disabled={isLocked}
                    className="mt-2 py-1.5 px-3 rounded-lg border border-dashed border-slate-300 text-slate-500 hover:text-indigo-600 hover:border-indigo-500 text-[11px] font-medium flex items-center gap-1.5 transition"
                  >
                    <Plus size={13} />
                    <span>Добавить вариант ответа</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Global save/add visual actions */}
      <div className="bg-slate-50 rounded-2xl border border-slate-200 p-6 flex flex-col md:flex-row gap-3 justify-between items-center select-none shadow-sm">
        <button
          onClick={handleAddQuestion}
          disabled={isLocked || saveToast === 'saving'}
          className="w-full md:w-auto py-3 px-5 border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 font-bold text-xs rounded-xl transition flex items-center justify-center gap-2"
        >
          <Plus size={16} />
          <span>Добавить новый вопрос в квиз</span>
        </button>

        <button
          onClick={handleSaveGroup}
          disabled={isLocked}
          className="w-full md:w-auto py-3 px-8 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl transition shadow-lg shadow-indigo-500/10 flex items-center justify-center gap-2"
        >
          {saveToast === 'saving' ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
          <span>Сохранить изменения</span>
        </button>
      </div>

      {/* Local manual info footer */}
      <div className="bg-slate-100 border border-slate-200 rounded-2xl p-5 flex gap-4 text-xs text-slate-600">
        <HelpCircle size={18} className="translate-y-0.5 shrink-0 text-slate-400" />
        <div className="space-y-1">
          <p className="font-semibold text-slate-800 font-sans">Обеспечение качества контента для Telegram</p>
          <p className="leading-relaxed">Конструктор накладывает требования разметки: вопросы не превышают 300 символов, объяснение строго ограничено 200 символами. При сохранении, если у Вас останутся ошибки, группа зафиксирует за собой желтый статус <code className="bg-amber-100 text-amber-800 rounded px-1 text-[10px] font-bold">NEEDS-REVIEW</code> и попросит исправить.</p>
        </div>
      </div>
    </div>
  );
}
