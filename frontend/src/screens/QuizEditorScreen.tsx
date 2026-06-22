import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Image as ImageIcon,
  Loader2,
  Plus,
  Save,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Panel, PanelBody, PanelHeader } from '../components/ui/Panel';

export type QuizEditorQuestion = {
  id: string;
  question: string;
  options: string[];
  correct?: number | null;
  explanation?: string;
  context?: string;
  media?: string[];
  warnings?: string[];
  quality_flags?: string[];
  needs_distractor_review?: boolean;
  [key: string]: unknown;
};

export type QuizEditorGroup = {
  id: string;
  name: string;
  allow_duplicate_questions?: boolean;
  date?: string;
  description?: string;
  questions: QuizEditorQuestion[];
  status?: 'draft' | 'review' | 'ready' | string;
  [key: string]: unknown;
};

export type QuizEditorExitRequest = {
  currentGroupId?: string;
  hasUnsavedChanges: boolean;
  nextGroupId?: string;
  proceed: () => void;
  reason: 'close' | 'switch-group';
};

type SaveState = 'idle' | 'saving' | 'saved' | 'error';
type EditorTab = 'all' | 'issues';
type IssueSeverity = 'critical' | 'warning';
type DismissibleIssue =
  | { kind: 'array'; field: 'warnings' | 'quality_flags'; index: number; message: string }
  | { kind: 'boolean'; field: 'needs_distractor_review' }
  | { kind: 'local'; issueId: string }
  | { kind: 'validation'; issueId: string };

type EditorIssue = {
  dismissible?: DismissibleIssue;
  id: string;
  ignored?: boolean;
  message: string;
  qIndex: number;
  severity: IssueSeverity;
  title: string;
};

type SaveQuizGroupHandler = (groupId: string, updatedGroup: QuizEditorGroup) => void | Promise<void>;
type ValidationReportIssuePayload = Record<string, unknown>;
type ValidationReportLike = {
  errors?: ValidationReportIssuePayload[];
  warnings?: ValidationReportIssuePayload[];
};
type ValidateQuizGroupHandler = (groupId: string, updatedGroup: QuizEditorGroup) => ValidationReportLike | void | Promise<ValidationReportLike | void>;

export type QuizEditorScreenProps = {
  isLocked?: boolean;
  onChangeDraft?: SaveQuizGroupHandler;
  onReadyForLaunch?: SaveQuizGroupHandler;
  onRequestExit?: (request: QuizEditorExitRequest) => void;
  onSelectedGroupChange?: (groupId: string) => void;
  onValidateJson?: ValidateQuizGroupHandler;
  quizGroup?: QuizEditorGroup | null;
  quizGroups?: QuizEditorGroup[];
  quizTitle?: string;
  questions?: QuizEditorQuestion[];
  resolveMediaUrl?: (path: string) => string;
  saveQuizGroup?: SaveQuizGroupHandler;
  selectedGroupId?: string;
  updateQuizGroup?: SaveQuizGroupHandler;
  uploadMedia?: (file: File) => Promise<string>;
};

const MAX_OPTIONS = 10;
const OPTION_LIMIT = 100;
const MIN_OPTIONS_FOR_READY = 3;
const QUESTION_LIMIT = 255;
const EXPLANATION_LIMIT = 200;
const MAX_QUESTIONS_FOR_UPLOAD = 200;

function cloneQuestions(questions: QuizEditorQuestion[]): QuizEditorQuestion[] {
  return questions.map((question) => ({
    ...question,
    media: Array.isArray(question.media) ? [...question.media] : [],
    options: Array.isArray(question.options) ? [...question.options] : [],
  }));
}

function makeDraftGroup(questions: QuizEditorQuestion[], title = 'Новый квиз'): QuizEditorGroup {
  return {
    id: 'draft',
    name: title,
    allow_duplicate_questions: false,
    questions,
    status: 'draft',
  };
}

function isValidCorrectIndex(correct: unknown, optionsCount: number): correct is number {
  return Number.isInteger(correct) && (correct as number) >= 0 && (correct as number) < optionsCount;
}

function issueText(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function issueIndex(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function questionTextKey(text: string): string {
  return text.trim().toLocaleLowerCase('ru-RU');
}

function duplicateQuestionIndexes(message: string): number[] {
  const match = message.match(/#(\d+)\s+and\s+#(\d+)/i);
  if (!match) return [];
  return [Number(match[1]), Number(match[2])].filter((value) => Number.isFinite(value) && value > 0);
}

function validationReportIssues(report: ValidationReportLike | void, questionCount: number): EditorIssue[] {
  if (!report) return [];

  const mapped: EditorIssue[] = [];
  const append = (payload: ValidationReportIssuePayload, severity: IssueSeverity, index: number) => {
    const code = issueText(payload.code, severity === 'critical' ? 'validation_error' : 'validation_warning');
    const message = issueText(payload.message, severity === 'critical' ? 'Backend проверка нашла ошибку.' : 'Backend проверка нашла предупреждение.');
    const indexes = duplicateQuestionIndexes(message);
    const targetIndexes = indexes.length > 0 ? indexes : [Math.max(1, issueIndex(payload.index) ?? 1)];

    targetIndexes.forEach((oneBasedIndex) => {
      const qIndex = Math.min(Math.max(oneBasedIndex - 1, 0), Math.max(questionCount - 1, 0));
      const issueId = `backend-${severity}-${code}-${oneBasedIndex}-${index}`;
      mapped.push({
        dismissible: severity === 'warning' ? { issueId, kind: 'validation' } : undefined,
        id: issueId,
        message,
        qIndex,
        severity,
        title: code === 'invalid_question' && message.includes('Duplicate question text')
          ? 'Дублируется текст вопроса'
          : severity === 'critical' ? 'Ошибка проверки JSON' : 'Предупреждение проверки JSON',
      });
    });
  };

  report.errors?.forEach((payload, index) => append(payload, 'critical', index));
  report.warnings?.forEach((payload, index) => append(payload, 'warning', index));
  return mapped;
}

function collectDuplicateQuestionIssues(questions: QuizEditorQuestion[]): EditorIssue[] {
  const issues: EditorIssue[] = [];
  const seen = new Map<string, number>();

  questions.forEach((question, qIndex) => {
    const key = questionTextKey(question.question || '');
    if (!key) return;

    const firstIndex = seen.get(key);
    if (firstIndex === undefined) {
      seen.set(key, qIndex);
      return;
    }

    issues.push({
      id: `duplicate-question-${firstIndex + 1}-${qIndex + 1}`,
      message: `Текст вопроса повторяет вопрос ${firstIndex + 1}. Измените формулировку или удалите дубль перед запуском.`,
      qIndex,
      severity: 'critical',
      title: 'Дублируется текст вопроса',
    });
  });

  return issues;
}

function collectUploadLimitIssues(questions: QuizEditorQuestion[]): EditorIssue[] {
  if (questions.length <= MAX_QUESTIONS_FOR_UPLOAD) return [];

  const issueId = 'too-many-questions-' + questions.length;
  return [{
    dismissible: { issueId, kind: 'local' },
    id: issueId,
    message: 'В квизе ' + questions.length + ' вопросов, текущий uploader поддерживает безопасный запуск до ' + MAX_QUESTIONS_FOR_UPLOAD + '. Если запускаете квиз частями, эту критичную проверку можно игнорировать.',
    qIndex: Math.min(Math.max(0, MAX_QUESTIONS_FOR_UPLOAD), Math.max(0, questions.length - 1)),
    severity: 'critical',
    title: 'Больше 200 вопросов',
  }];
}

function isBlockingCriticalIssue(issue: EditorIssue): boolean {
  return issue.severity === 'critical' && !issue.ignored;
}

function collectQuestionIssues(question: QuizEditorQuestion, qIndex: number): EditorIssue[] {
  const issues: EditorIssue[] = [];
  const questionId = `${question.id || 'question'}-${qIndex + 1}`;
  const options = Array.isArray(question.options) ? question.options : [];
  const normalizedOptions = options.map((option) => option.trim().toLocaleLowerCase('ru-RU'));
  const seenOptions = new Map<string, number>();

  if (!question.question.trim()) {
    issues.push({
      id: `${questionId}-empty-question`,
      message: 'Заполните текст вопроса перед запуском квиза.',
      qIndex,
      severity: 'critical',
      title: 'Нет текста вопроса',
    });
  }

  if (question.question.length > QUESTION_LIMIT) {
    issues.push({
      id: `${questionId}-question-limit`,
      message: `Сократите вопрос до ${QUESTION_LIMIT} символов.`,
      qIndex,
      severity: 'critical',
      title: 'Превышен лимит вопроса',
    });
  }

  if (options.length < MIN_OPTIONS_FOR_READY) {
    issues.push({
      id: `${questionId}-few-options`,
      message: `Добавьте минимум ${MIN_OPTIONS_FOR_READY} варианта ответа.`,
      qIndex,
      severity: 'critical',
      title: 'Меньше 3 вариантов',
    });
  }

  if (!isValidCorrectIndex(question.correct, options.length)) {
    issues.push({
      id: `${questionId}-missing-correct`,
      message: 'Выберите правильный ответ, чтобы квиз можно было запустить.',
      qIndex,
      severity: 'critical',
      title: 'Нет правильного ответа',
    });
  }

  normalizedOptions.forEach((option, optionIndex) => {
    if (!option) {
      issues.push({
        id: `${questionId}-empty-option-${optionIndex}`,
        message: `Заполните вариант ${optionIndex + 1} или удалите его.`,
        qIndex,
        severity: 'critical',
        title: 'Пустой вариант',
      });
      return;
    }

    if (option.length > OPTION_LIMIT) {
      issues.push({
        id: `${questionId}-option-limit-${optionIndex}`,
        message: `Сократите вариант ${optionIndex + 1} до ${OPTION_LIMIT} символов. Сейчас ${option.length}.`,
        qIndex,
        severity: 'critical',
        title: 'Длинный вариант ответа',
      });
    }

    const firstIndex = seenOptions.get(option);
    if (firstIndex !== undefined) {
      issues.push({
        id: `${questionId}-duplicate-option-${optionIndex}`,
        message: `Вариант ${optionIndex + 1} повторяет вариант ${firstIndex + 1}.`,
        qIndex,
        severity: 'warning',
        title: 'Дублируется вариант',
      });
      return;
    }

    seenOptions.set(option, optionIndex);
  });

  if ((question.explanation || '').length > EXPLANATION_LIMIT) {
    issues.push({
      id: `${questionId}-explanation-limit`,
      message: `Сократите объяснение до ${EXPLANATION_LIMIT} символов.`,
      qIndex,
      severity: 'warning',
      title: 'Длинное объяснение',
    });
  }

  if (question.needs_distractor_review) {
    issues.push({
      dismissible: { field: 'needs_distractor_review', kind: 'boolean' },
      id: `${questionId}-distractor-review`,
      message: 'Проверьте distractors вручную перед запуском.',
      qIndex,
      severity: 'warning',
      title: 'Нужна проверка вариантов',
    });
  }

  (question.warnings || []).forEach((message, messageIndex) => {
    issues.push({
      dismissible: { field: 'warnings', index: messageIndex, kind: 'array', message },
      id: `${questionId}-backend-warning-${messageIndex}`,
      message,
      qIndex,
      severity: 'warning',
      title: 'Предупреждение проверки',
    });
  });

  (question.quality_flags || []).forEach((message, messageIndex) => {
    issues.push({
      dismissible: { field: 'quality_flags', index: messageIndex, kind: 'array', message },
      id: `${questionId}-quality-warning-${messageIndex}`,
      message,
      qIndex,
      severity: 'warning',
      title: 'Предупреждение проверки',
    });
  });

  return issues;
}

function buildUpdatedGroup(
  group: QuizEditorGroup,
  questions: QuizEditorQuestion[],
  name = group.name,
  allowDuplicateQuestions = Boolean(group.allow_duplicate_questions),
): QuizEditorGroup {
  const issues = questions.flatMap((question, index) => collectQuestionIssues(question, index));
  const hasCriticalIssues = issues.some((issue) => issue.severity === 'critical');
  const hasIssues = issues.length > 0;

  return {
    ...group,
    name: name.trim() || group.name || 'Новый квиз',
    allow_duplicate_questions: allowDuplicateQuestions,
    questions: cloneQuestions(questions),
    status: hasCriticalIssues || hasIssues ? 'review' : 'ready',
  };
}

function mediaFileName(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() || path;
}

function defaultResolveMediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path) || path.startsWith('/')) return path;
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return '#';

  return path
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .split('/')
    .map(encodeURIComponent)
    .join('/');
}

function formatAutosaveText(dirty: boolean, saveState: SaveState): string {
  if (saveState === 'saving') return 'сохранение...';
  if (saveState === 'saved') return 'сохранено вручную';
  if (dirty) return 'есть несохраненные изменения';
  return 'автосейв ожидает подключения';
}

export default function QuizEditorScreen({
  isLocked = false,
  onChangeDraft,
  onReadyForLaunch,
  onRequestExit,
  onSelectedGroupChange,
  onValidateJson,
  quizGroup,
  quizGroups,
  quizTitle,
  questions: propQuestions,
  resolveMediaUrl = defaultResolveMediaUrl,
  saveQuizGroup,
  selectedGroupId,
  updateQuizGroup,
  uploadMedia,
}: QuizEditorScreenProps) {
  const groups = useMemo(() => {
    if (quizGroups?.length) return quizGroups;
    if (quizGroup) return [quizGroup];
    if (propQuestions) return [makeDraftGroup(propQuestions, quizTitle)];
    return [];
  }, [propQuestions, quizGroup, quizGroups, quizTitle]);

  const [internalGroupId, setInternalGroupId] = useState(groups[0]?.id || '');
  const activeGroupId = selectedGroupId ?? internalGroupId;
  const currentGroup = groups.find((group) => group.id === activeGroupId) || groups[0] || null;
  const [draftName, setDraftName] = useState(currentGroup?.name || '');
  const [allowDuplicateQuestions, setAllowDuplicateQuestions] = useState(Boolean(currentGroup?.allow_duplicate_questions));
  const [draftQuestions, setDraftQuestions] = useState<QuizEditorQuestion[]>(() => cloneQuestions(currentGroup?.questions || []));
  const [dirty, setDirty] = useState(false);
  const [editorTab, setEditorTab] = useState<EditorTab>('all');
  const [pendingGroupId, setPendingGroupId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [saveMessage, setSaveMessage] = useState('');
  const [validationIssues, setValidationIssues] = useState<EditorIssue[]>([]);
  const [ignoredLocalIssueIds, setIgnoredLocalIssueIds] = useState<Set<string>>(() => new Set());
  const [uploadingQuestionIndex, setUploadingQuestionIndex] = useState<number | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    if (!groups.length) {
      setInternalGroupId('');
      return;
    }

    if (!activeGroupId || !groups.some((group) => group.id === activeGroupId)) {
      const nextGroupId = groups[0].id;
      setInternalGroupId(nextGroupId);
      onSelectedGroupChange?.(nextGroupId);
    }
  }, [activeGroupId, groups, onSelectedGroupChange]);

  useEffect(() => {
    setDraftName(currentGroup?.name || '');
    setAllowDuplicateQuestions(Boolean(currentGroup?.allow_duplicate_questions));
    setDraftQuestions(cloneQuestions(currentGroup?.questions || []));
    setDirty(false);
    setPendingGroupId(null);
    setSaveState('idle');
    setSaveMessage('');
    setValidationIssues([]);
    setIgnoredLocalIssueIds(new Set());
  }, [currentGroup?.id]);

  const rawLocalIssues = useMemo(
    () => [
      ...draftQuestions.flatMap((question, index) => collectQuestionIssues(question, index)),
      ...(allowDuplicateQuestions ? [] : collectDuplicateQuestionIssues(draftQuestions)),
      ...collectUploadLimitIssues(draftQuestions),
    ],
    [allowDuplicateQuestions, draftQuestions],
  );
  const localIssues = useMemo(
    () => rawLocalIssues.map((issue) => (
      issue.dismissible?.kind === 'local' && ignoredLocalIssueIds.has(issue.dismissible.issueId)
        ? { ...issue, ignored: true }
        : issue
    )),
    [ignoredLocalIssueIds, rawLocalIssues],
  );
  const issues = useMemo(() => [...localIssues, ...validationIssues], [localIssues, validationIssues]);
  const criticalIssues = issues.filter((issue) => issue.severity === 'critical');
  const blockingCriticalIssues = issues.filter(isBlockingCriticalIssue);
  const warningIssues = issues.filter((issue) => issue.severity === 'warning');
  const issuesByQuestion = useMemo(() => {
    const grouped = new Map<number, EditorIssue[]>();
    issues.forEach((issue) => {
      grouped.set(issue.qIndex, [...(grouped.get(issue.qIndex) || []), issue]);
    });
    return grouped;
  }, [issues]);
  const visibleQuestions = editorTab === 'issues'
    ? draftQuestions.filter((_, index) => (issuesByQuestion.get(index)?.length || 0) > 0)
    : draftQuestions;
  const saveHandler = saveQuizGroup || updateQuizGroup;
  const canSave = Boolean(currentGroup && saveHandler && !isLocked && saveState !== 'saving');

  const markChanged = (nextQuestions: QuizEditorQuestion[], nextName = draftName, nextAllowDuplicateQuestions = allowDuplicateQuestions) => {
    setDraftQuestions(nextQuestions);
    setAllowDuplicateQuestions(nextAllowDuplicateQuestions);
    setValidationIssues([]);
    setDirty(true);
    setSaveState('idle');
    if (currentGroup) {
      void Promise.resolve(onChangeDraft?.(currentGroup.id, buildUpdatedGroup(currentGroup, nextQuestions, nextName, nextAllowDuplicateQuestions))).catch((error: unknown) => {
        setSaveState('error');
        setSaveMessage(error instanceof Error ? error.message : 'Не удалось обновить черновик');
      });
    }
  };

  const handleRenameQuiz = (nextName: string) => {
    setDraftName(nextName);
    markChanged(draftQuestions, nextName, allowDuplicateQuestions);
  };

  const handleToggleAllowDuplicates = (checked: boolean) => {
    markChanged(draftQuestions, draftName, checked);
  };

  const applyQuestionPatch = (qIndex: number, patch: Partial<QuizEditorQuestion>) => {
    markChanged(draftQuestions.map((question, index) => (index === qIndex ? { ...question, ...patch } : question)));
  };

  const handleDismissIssue = (qIndex: number, issue: EditorIssue) => {
    const dismissible = issue.dismissible;
    if (!dismissible || isLocked) return;
    const canIgnore = issue.severity === 'warning' || dismissible.kind === 'local';
    if (!canIgnore) return;

    if (dismissible.kind === 'validation') {
      setValidationIssues((current) => current.filter((validationIssue) => validationIssue.id !== dismissible.issueId));
      return;
    }

    if (dismissible.kind === 'local') {
      setIgnoredLocalIssueIds((current) => new Set(current).add(dismissible.issueId));
      return;
    }

    const nextQuestions = draftQuestions.map((question, index) => {
      if (index !== qIndex) return question;

      if (dismissible.kind === 'boolean') {
        return {
          ...question,
          [dismissible.field]: false,
        };
      }

      const field = dismissible.field;
      const current = Array.isArray(question[field]) ? [...question[field]] : [];
      if (current[dismissible.index] === dismissible.message) {
        current.splice(dismissible.index, 1);
      } else {
        const matchingIndex = current.findIndex((message) => message === dismissible.message);
        if (matchingIndex >= 0) current.splice(matchingIndex, 1);
      }

      return {
        ...question,
        [field]: current,
      };
    });

    markChanged(nextQuestions);
  };

  const handleSelectGroup = (nextGroupId: string) => {
    if (nextGroupId === activeGroupId) return;

    const proceed = () => {
      setInternalGroupId(nextGroupId);
      onSelectedGroupChange?.(nextGroupId);
      setPendingGroupId(null);
    };

    if (!dirty) {
      proceed();
      return;
    }

    if (onRequestExit) {
      onRequestExit({
        currentGroupId: currentGroup?.id,
        hasUnsavedChanges: dirty,
        nextGroupId,
        proceed,
        reason: 'switch-group',
      });
      return;
    }

    setPendingGroupId(nextGroupId);
  };

  const handleRequestExit = () => {
    if (!onRequestExit) return;

    onRequestExit({
      currentGroupId: currentGroup?.id,
      hasUnsavedChanges: dirty,
      proceed: () => undefined,
      reason: 'close',
    });
  };

  const handleDiscardAndSwitch = () => {
    if (!pendingGroupId) return;
    setInternalGroupId(pendingGroupId);
    onSelectedGroupChange?.(pendingGroupId);
    setPendingGroupId(null);
  };

  const handleModifyOption = (qIndex: number, optIndex: number, value: string) => {
    const nextQuestions = draftQuestions.map((question, questionIndex) => {
      if (questionIndex !== qIndex) return question;
      return {
        ...question,
        options: question.options.map((option, optionIndex) => (optionIndex === optIndex ? value : option)),
      };
    });
    markChanged(nextQuestions);
  };

  const handleAddOption = (qIndex: number) => {
    const nextQuestions = draftQuestions.map((question, questionIndex) => {
      if (questionIndex !== qIndex || question.options.length >= MAX_OPTIONS) return question;
      return {
        ...question,
        options: [...question.options, `Новый вариант ${question.options.length + 1}`],
      };
    });
    markChanged(nextQuestions);
  };

  const handleRemoveOption = (qIndex: number, optIndex: number) => {
    const nextQuestions = draftQuestions.map((question, questionIndex) => {
      if (questionIndex !== qIndex || question.options.length <= 2) return question;

      const nextOptions = question.options.filter((_, optionIndex) => optionIndex !== optIndex);
      const currentCorrect = question.correct;
      let nextCorrect: number | null | undefined = currentCorrect;

      if (currentCorrect === optIndex) {
        nextCorrect = null;
      } else if (typeof currentCorrect === 'number' && currentCorrect > optIndex) {
        nextCorrect = currentCorrect - 1;
      }

      return {
        ...question,
        correct: nextCorrect,
        options: nextOptions,
      };
    });
    markChanged(nextQuestions);
  };

  const handleAddQuestion = () => {
    markChanged([
      ...draftQuestions,
      {
        correct: null,
        id: `q_new_${Date.now()}`,
        options: ['Вариант A', 'Вариант B', 'Вариант C'],
        question: 'Введите текст вопроса',
      },
    ]);
  };

  const handleRemoveQuestion = (qIndex: number) => {
    markChanged(draftQuestions.filter((_, index) => index !== qIndex));
  };

  const handleUploadMedia = async (qIndex: number, file: File | null | undefined) => {
    if (!file || !uploadMedia || isLocked) return;

    setUploadingQuestionIndex(qIndex);
    try {
      const uploadedPath = await uploadMedia(file);
      const nextQuestions = draftQuestions.map((question, index) => {
        if (index !== qIndex) return question;
        return {
          ...question,
          media: [...(question.media || []), uploadedPath],
        };
      });
      markChanged(nextQuestions);
    } catch (error) {
      setSaveState('error');
      setSaveMessage(error instanceof Error ? error.message : 'Не удалось загрузить медиа');
    } finally {
      setUploadingQuestionIndex(null);
    }
  };

  const handleRemoveMedia = (qIndex: number, mediaIndex: number) => {
    const nextQuestions = draftQuestions.map((question, index) => {
      if (index !== qIndex) return question;
      return {
        ...question,
        media: (question.media || []).filter((_, itemIndex) => itemIndex !== mediaIndex),
      };
    });
    markChanged(nextQuestions);
  };

  const handleCheckJson = async () => {
    setValidationIssues([]);
    setSaveState('idle');
    setSaveMessage('');
    setEditorTab(localIssues.length > 0 ? 'issues' : 'all');
    setLastCheckedAt(new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }));

    if (!currentGroup || !onValidateJson) return;

    if (localIssues.some(isBlockingCriticalIssue)) {
      return;
    }

    try {
      const report = await onValidateJson(currentGroup.id, buildUpdatedGroup(currentGroup, draftQuestions, draftName, allowDuplicateQuestions));
      const nextValidationIssues = validationReportIssues(report, draftQuestions.length);
      setValidationIssues(nextValidationIssues);
      setEditorTab(nextValidationIssues.length > 0 ? 'issues' : 'all');
    } catch {
      setSaveState('error');
      setSaveMessage('Проверка JSON не выполнена');
    }
  };

  const handleSave = async () => {
    if (!currentGroup || !saveHandler || saveState === 'saving') return;

    setSaveState('saving');
    setSaveMessage('Сохранение изменений...');
    try {
      await saveHandler(currentGroup.id, buildUpdatedGroup(currentGroup, draftQuestions, draftName, allowDuplicateQuestions));
      setDirty(false);
      setSaveState('saved');
      setSaveMessage('Изменения сохранены');
    } catch (error) {
      setSaveState('error');
      setSaveMessage(error instanceof Error ? error.message : 'Не удалось сохранить изменения');
    }
  };

  const handleReadyForLaunch = async () => {
    if (!currentGroup || blockingCriticalIssues.length > 0) {
      setEditorTab('issues');
      return;
    }

    try {
      await onReadyForLaunch?.(currentGroup.id, buildUpdatedGroup(currentGroup, draftQuestions, draftName, allowDuplicateQuestions));
    } catch (error) {
      setSaveState('error');
      setSaveMessage(error instanceof Error ? error.message : 'Не удалось подготовить квиз к запуску');
    }
  };

  const scrollToQuestion = (qIndex: number) => {
    document.getElementById(`quiz-editor-question-${qIndex}`)?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  };

  if (groups.length === 0 || !currentGroup) {
    return (
      <Panel>
        <PanelBody className="py-12 text-center">
          <p className="text-base font-semibold text-gray-950">Нет квиза для редактирования</p>
          <p className="mt-2 text-sm text-gray-500">Передайте `quizGroup`, `quizGroups` или `questions` через props.</p>
        </PanelBody>
      </Panel>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 border-b border-gray-200 pb-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <h1 className="text-3xl font-bold tracking-normal text-gray-950">Редактор квиза</h1>
          <p className="mt-2 text-sm text-gray-600">
            {(draftName.trim() || currentGroup.name)} · {draftQuestions.length} вопросов · {criticalIssues.length} ошибок · {formatAutosaveText(dirty, saveState)}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 xl:justify-end">
          <Button icon={<CheckCircle2 className="size-4" />} onClick={handleCheckJson} size="sm" variant="primary">
            Проверить JSON
          </Button>
          <Button disabled={!canSave} icon={<Save className="size-4" />} loading={saveState === 'saving'} onClick={handleSave} size="sm">
            Сохранить
          </Button>
          <Button
            disabled={isLocked || blockingCriticalIssues.length > 0}
            icon={<Check className="size-4" />}
            onClick={handleReadyForLaunch}
            size="sm"
            variant="outline"
          >
            Готово к запуску
          </Button>
          {onRequestExit && (
            <Button className="px-2 text-gray-700 hover:bg-transparent hover:text-gray-950" onClick={handleRequestExit} size="sm" variant="ghost">
              Закрыть
            </Button>
          )}
        </div>
      </div>

      <Panel>
        <PanelBody className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(240px,360px)_auto] lg:items-end">
          <label className="block min-w-0 flex-1 space-y-1.5">
            <span className="text-sm font-semibold text-gray-700">Квиз для редактирования</span>
            <span className="relative block">
              <select
                className="min-h-10 w-full appearance-none rounded-md border border-gray-200 bg-white px-3 py-2 pr-9 text-sm font-semibold text-gray-950 focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:bg-gray-50 disabled:text-gray-500"
                disabled={isLocked || groups.length <= 1}
                onChange={(event) => handleSelectGroup(event.target.value)}
                value={currentGroup.id}
              >
                {groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {(group.id === currentGroup.id ? draftName.trim() || group.name : group.name)} ({group.questions.length})
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-gray-400" aria-hidden="true" />
            </span>
          </label>
          <label className="block min-w-0 space-y-1.5">
            <span className="text-sm font-semibold text-gray-700">Название квиза</span>
            <input
              className="min-h-10 w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-950 focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:bg-gray-50 disabled:text-gray-500"
              disabled={isLocked}
              onChange={(event) => handleRenameQuiz(event.target.value)}
              placeholder="Введите название квиза"
              value={draftName}
            />
          </label>
          <label className="flex min-h-10 items-center gap-3 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 lg:col-span-2">
            <input
              checked={allowDuplicateQuestions}
              className="size-4 accent-[#E85D8F] disabled:cursor-not-allowed"
              disabled={isLocked}
              onChange={(event) => handleToggleAllowDuplicates(event.target.checked)}
              type="checkbox"
            />
            <span className="min-w-0">
              <span className="block font-semibold text-gray-950">Разрешить дубли вопросов</span>
              <span className="block text-xs text-gray-500">Только для этого квиза; одинаковые тексты не будут блокировать запуск.</span>
            </span>
          </label>
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-500">
            <Badge tone={currentGroup.status === 'ready' ? 'success' : currentGroup.status === 'review' ? 'warning' : 'neutral'}>
              {currentGroup.status === 'ready' ? 'готов' : currentGroup.status === 'review' ? 'нужно проверить' : 'черновик'}
            </Badge>
            <span>{groups.length} всего</span>
          </div>
        </PanelBody>
      </Panel>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-md border border-gray-200 bg-white p-1">
            <button
              className={[
                'min-h-9 rounded px-3 text-sm font-semibold transition-colors',
                editorTab === 'all' ? 'bg-[#FCE7F0] text-[#E85D8F]' : 'text-gray-600 hover:bg-gray-50',
              ].join(' ')}
              onClick={() => setEditorTab('all')}
              type="button"
            >
              Все вопросы
            </button>
            <button
              className={[
                'min-h-9 rounded px-3 text-sm font-semibold transition-colors',
                editorTab === 'issues' ? 'bg-[#FCE7F0] text-[#E85D8F]' : 'text-gray-600 hover:bg-gray-50',
              ].join(' ')}
              onClick={() => setEditorTab('issues')}
              type="button"
            >
              Только ошибки
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm text-gray-500">
          <Badge tone={criticalIssues.length > 0 ? 'danger' : 'success'}>
            {criticalIssues.length > 0 ? `${criticalIssues.length} критично` : 'Критичных ошибок нет'}
          </Badge>
          <Badge tone={warningIssues.length > 0 ? 'warning' : 'neutral'}>{warningIssues.length} предупреждений</Badge>
          <span>{lastCheckedAt ? `проверено в ${lastCheckedAt}` : 'проверка локальная'}</span>
        </div>
      </div>

      {pendingGroupId && (
        <Panel className="border-amber-200 bg-amber-50">
          <PanelBody className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 size-5 shrink-0 text-amber-600" aria-hidden="true" />
              <div>
                <p className="font-semibold text-amber-950">Есть несохраненные изменения</p>
                <p className="mt-1 text-sm text-amber-800">Сохраните текущий квиз или перейдите без сохранения.</p>
              </div>
            </div>
            <div className="flex gap-2">
              <Button disabled={!canSave} onClick={handleSave} size="sm" variant="outline">
                Сохранить
              </Button>
              <Button onClick={handleDiscardAndSwitch} size="sm" variant="ghost">
                Перейти без сохранения
              </Button>
            </div>
          </PanelBody>
        </Panel>
      )}

      {saveState !== 'idle' && (
        <div
          className={[
            'fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-lg border px-4 py-3 text-sm font-semibold shadow-xl',
            saveState === 'error'
              ? 'border-red-500 bg-red-600 text-white'
              : saveState === 'saved'
                ? 'border-emerald-500 bg-emerald-600 text-white'
                : 'border-gray-800 bg-gray-950 text-white',
          ].join(' ')}
          role="status"
        >
          {saveState === 'saving' ? <Loader2 className="size-4 animate-spin" /> : saveState === 'error' ? <AlertCircle className="size-4" /> : <CheckCircle2 className="size-4" />}
          <span>{saveMessage}</span>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Panel className="h-fit xl:sticky xl:top-5 xl:flex xl:max-h-[calc(100vh-2.5rem)] xl:flex-col">
          <PanelHeader
            description={issues.length > 0 ? 'Кликните, чтобы перейти к вопросу' : 'Все карточки готовы к запуску'}
            title="Ошибки"
            action={<Badge tone={issues.length > 0 ? 'danger' : 'success'}>{issues.length} всего</Badge>}
          />
          <PanelBody className="flex min-h-0 flex-col gap-3 pt-4">
            {issues.length === 0 ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 xl:shrink-0">
                Нет найденных ошибок в локальной проверке.
              </div>
            ) : (
              <div className="min-h-0 space-y-2 overflow-y-auto pr-1 xl:max-h-[calc(100vh-13rem)]">
                {issues.map((issue) => (
                  <button
                    className={[
                      'w-full rounded-md border p-3 text-left transition-colors',
                      issue.severity === 'critical'
                        ? 'border-red-200 bg-red-50 text-red-900 hover:bg-red-100'
                        : 'border-amber-200 bg-amber-50 text-amber-900 hover:bg-amber-100',
                    ].join(' ')}
                    key={issue.id}
                    onClick={() => scrollToQuestion(issue.qIndex)}
                    type="button"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-bold">Вопрос {issue.qIndex + 1}</span>
                      <Badge tone={issue.severity === 'critical' ? 'danger' : 'warning'}>
                        {issue.severity === 'critical' ? 'критично' : 'warning'}
                      </Badge>
                    </div>
                    <p className="mt-1 text-sm font-semibold">{issue.title}</p>
                    <p className="mt-1 text-xs leading-5 opacity-80">{issue.message}</p>
                  </button>
                ))}
              </div>
            )}

            <Button className="w-full" icon={<CheckCircle2 className="size-4" />} onClick={handleCheckJson} variant="outline">
              Проверить снова
            </Button>
          </PanelBody>
        </Panel>

        <div className="space-y-4">
          {visibleQuestions.map((question) => {
            const realIndex = draftQuestions.indexOf(question);
            const questionIssues = issuesByQuestion.get(realIndex) || [];
            const questionCriticalIssues = questionIssues.filter((issue) => issue.severity === 'critical');
            const questionWarningIssues = questionIssues.filter((issue) => issue.severity === 'warning');
            const isReady = questionIssues.length === 0;
            const mediaItems = Array.isArray(question.media) ? question.media.filter(Boolean) : [];
            const hasSelectedCorrect = isValidCorrectIndex(question.correct, question.options.length);

            return (
              <Panel
                className={[
                  'scroll-mt-6 transition-shadow',
                  questionCriticalIssues.length > 0
                    ? 'border-red-300 shadow-[0_1px_8px_rgba(229,72,77,0.08)]'
                    : questionWarningIssues.length > 0
                      ? 'border-amber-300'
                      : '',
                ].join(' ')}
                id={`quiz-editor-question-${realIndex}`}
                key={`${question.id || 'question'}-${realIndex}`}
              >
                <PanelHeader
                  action={
                    <button
                      className="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isLocked}
                      onClick={() => handleRemoveQuestion(realIndex)}
                      title="Удалить вопрос"
                      type="button"
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                    </button>
                  }
                  title={`Вопрос ${realIndex + 1} из ${draftQuestions.length}`}
                >
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isReady && <Badge tone="success">Готов</Badge>}
                    {questionCriticalIssues.length > 0 && <Badge tone="danger">Ошибка: {questionCriticalIssues[0].title.toLocaleLowerCase('ru-RU')}</Badge>}
                    {questionWarningIssues.length > 0 && <Badge tone="warning">{questionWarningIssues.length} предупреждение</Badge>}
                  </div>
                </PanelHeader>

                <PanelBody className="space-y-4 pt-4">
                  {questionIssues.length > 0 && (
                    <div className="space-y-2">
                      {questionIssues.map((issue) => (
                        <div
                          className={[
                            'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                            issue.severity === 'critical'
                              ? 'border-red-200 bg-red-50 text-red-800'
                              : 'border-amber-200 bg-amber-50 text-amber-800',
                          ].join(' ')}
                          key={issue.id}
                        >
                          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                          <span className="min-w-0 flex-1">{issue.message}</span>
                          {issue.ignored && (
                            <Badge tone="neutral">игнорируется</Badge>
                          )}
                          {issue.dismissible && (issue.severity === 'warning' || issue.dismissible.kind === 'local') && !issue.ignored && (
                            <button
                              className={[
                                'flex size-7 shrink-0 items-center justify-center rounded-md border bg-white/80 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-50',
                                issue.severity === 'critical'
                                  ? 'border-red-200 text-red-700 hover:border-red-300 hover:text-red-950'
                                  : 'border-amber-200 text-amber-700 hover:border-amber-300 hover:text-amber-950',
                              ].join(' ')}
                              disabled={isLocked}
                              onClick={() => handleDismissIssue(realIndex, issue)}
                              title={issue.severity === 'critical' ? 'Игнорировать эту критичную проверку' : 'Убрать это предупреждение'}
                              type="button"
                            >
                              <X className="size-4" aria-hidden="true" />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_250px]">
                    <div className="space-y-4">
                      <label className="block">
                        <span className="text-sm font-semibold text-gray-800">Текст вопроса</span>
                        <textarea
                          className="mt-2 min-h-20 w-full resize-y rounded-md border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-950 focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:bg-gray-50 disabled:text-gray-500"
                          disabled={isLocked}
                          onChange={(event) => applyQuestionPatch(realIndex, { question: event.target.value })}
                          value={question.question}
                        />
                        <span className={['mt-1 block text-xs', question.question.length > QUESTION_LIMIT ? 'text-red-600' : 'text-gray-500'].join(' ')}>
                          {question.question.length} / {QUESTION_LIMIT} символов
                        </span>
                      </label>

                      <label className="block">
                        <span className="text-sm font-semibold text-gray-800">Объяснение (необязательно)</span>
                        <textarea
                          className="mt-2 min-h-20 w-full resize-y rounded-md border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:bg-gray-50 disabled:text-gray-500"
                          disabled={isLocked}
                          onChange={(event) => applyQuestionPatch(realIndex, { explanation: event.target.value })}
                          placeholder="Короткое объяснение правильного ответа"
                          value={question.explanation || ''}
                        />
                        <span className={['mt-1 block text-xs', (question.explanation || '').length > EXPLANATION_LIMIT ? 'text-red-600' : 'text-gray-500'].join(' ')}>
                          {(question.explanation || '').length} / {EXPLANATION_LIMIT} символов
                        </span>
                      </label>
                    </div>

                    <div className="space-y-3">
                      <label className="block">
                        <span className="text-sm font-semibold text-gray-800">Контекст</span>
                        <textarea
                          className="mt-2 min-h-24 w-full resize-y rounded-md border border-gray-200 bg-white p-3 text-sm leading-6 text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:bg-gray-50 disabled:text-gray-500"
                          disabled={isLocked}
                          onChange={(event) => applyQuestionPatch(realIndex, { context: event.target.value })}
                          placeholder="Текст контекста перед вопросом"
                          value={question.context || ''}
                        />
                      </label>

                      <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-gray-800">Медиа</span>
                          <label
                            className={[
                              'inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-md border border-gray-200 bg-white px-3 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100',
                              !uploadMedia || isLocked ? 'pointer-events-none opacity-50' : '',
                            ].join(' ')}
                          >
                            {uploadingQuestionIndex === realIndex ? <Loader2 className="size-4 animate-spin" /> : <UploadCloud className="size-4" />}
                            <span>{uploadingQuestionIndex === realIndex ? 'Загрузка' : 'Загрузить'}</span>
                            <input
                              accept="image/png,image/jpeg,image/webp,image/gif"
                              className="hidden"
                              disabled={!uploadMedia || isLocked || uploadingQuestionIndex === realIndex}
                              onChange={(event) => {
                                void handleUploadMedia(realIndex, event.target.files?.[0]);
                                event.target.value = '';
                              }}
                              type="file"
                            />
                          </label>
                        </div>

                        {mediaItems.length > 0 ? (
                          <div className="mt-3 grid grid-cols-2 gap-2">
                            {mediaItems.map((item, mediaIndex) => (
                              <div className="group relative overflow-hidden rounded-md border border-gray-200 bg-white" key={`${item}-${mediaIndex}`}>
                                <a href={resolveMediaUrl(item)} rel="noreferrer" target="_blank" title={item}>
                                  <img
                                    alt={`Медиа вопроса ${realIndex + 1}`}
                                    className="aspect-square w-full bg-gray-100 object-cover"
                                    src={resolveMediaUrl(item)}
                                  />
                                </a>
                                <button
                                  className="absolute right-1 top-1 flex size-7 items-center justify-center rounded-md border border-gray-200 bg-white/90 text-gray-500 opacity-0 transition-opacity hover:text-red-600 group-hover:opacity-100"
                                  disabled={isLocked}
                                  onClick={() => handleRemoveMedia(realIndex, mediaIndex)}
                                  title="Убрать медиа"
                                  type="button"
                                >
                                  <X className="size-4" aria-hidden="true" />
                                </button>
                                <span className="block truncate px-2 py-1 text-xs text-gray-500">{mediaFileName(item)}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="mt-3 flex items-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-500">
                            <ImageIcon className="size-4" aria-hidden="true" />
                            <span>Фото не прикреплено</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <h3 className="text-sm font-bold text-gray-950">Варианты ответов</h3>
                      <Button
                        disabled={isLocked || question.options.length >= MAX_OPTIONS}
                        icon={<Plus className="size-4" />}
                        onClick={() => handleAddOption(realIndex)}
                        size="sm"
                        variant="outline"
                      >
                        Добавить вариант
                      </Button>
                    </div>

                    <div className="grid gap-3 lg:grid-cols-2">
                      {question.options.map((option, optionIndex) => {
                        const isCorrect = hasSelectedCorrect && question.correct === optionIndex;

                        return (
                          <div
                            className={[
                              'flex items-center gap-3 rounded-md border p-3 transition-colors',
                              isCorrect ? 'border-emerald-300 bg-emerald-50' : 'border-gray-200 bg-white',
                            ].join(' ')}
                            key={`${question.id}-${optionIndex}`}
                          >
                            <button
                              className={[
                                'flex size-6 shrink-0 items-center justify-center rounded-full border transition-colors',
                                isCorrect ? 'border-emerald-500 bg-emerald-500 text-white' : 'border-gray-300 bg-white text-gray-400 hover:border-[#E85D8F]',
                              ].join(' ')}
                              disabled={isLocked}
                              onClick={() => applyQuestionPatch(realIndex, { correct: optionIndex })}
                              title="Сделать правильным ответом"
                              type="button"
                            >
                              {isCorrect ? <Check className="size-4" aria-hidden="true" /> : <CircleDot className="size-3" aria-hidden="true" />}
                            </button>

                            <input
                              className="min-h-10 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 text-sm text-gray-950 focus:border-gray-200 focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#E85D8F] disabled:text-gray-500"
                              disabled={isLocked}
                              onChange={(event) => handleModifyOption(realIndex, optionIndex, event.target.value)}
                              value={option}
                            />

                            {isCorrect && <Badge tone="success">правильный</Badge>}

                            <button
                              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                              disabled={isLocked || question.options.length <= 2}
                              onClick={() => handleRemoveOption(realIndex, optionIndex)}
                              title="Удалить вариант"
                              type="button"
                            >
                              <Trash2 className="size-4" aria-hidden="true" />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </PanelBody>
              </Panel>
            );
          })}

          {visibleQuestions.length === 0 && (
            <Panel>
              <PanelBody className="py-10 text-center">
                <p className="text-base font-semibold text-gray-950">Вопросов с ошибками нет</p>
                <p className="mt-2 text-sm text-gray-500">Переключитесь на вкладку «Все вопросы», чтобы продолжить редактирование.</p>
              </PanelBody>
            </Panel>
          )}

          <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-gray-50 p-4 sm:flex-row sm:items-center sm:justify-between">
            <Button disabled={isLocked} icon={<Plus className="size-4" />} onClick={handleAddQuestion} variant="outline">
              Добавить вопрос
            </Button>
            <Button disabled={!canSave} icon={<Save className="size-4" />} loading={saveState === 'saving'} onClick={handleSave} variant="primary">
              Сохранить изменения
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
