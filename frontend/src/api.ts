import {
  AccountProfilePublic,
  ActiveRunResponse,
  HealthResponse,
  JobEvent,
  JobSnapshot,
  QuizGroup,
  GroupSummary,
  RunStatusSnapshot,
  SettingsResponse,
  TelegramLoginAuthorizedResponse,
  TelegramLoginCodeResponse,
  TelegramLoginStartResponse,
  TelegramLoginStatusResponse,
  WaitForJobOptions,
} from './types';

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');

const ACCOUNT_MANAGEMENT_DISABLED =
  'Создание и редактирование Telegram credentials через веб-интерфейс отключено.';

export function mediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.replace(/\\/g, '/').replace(/^\/+/, '');
  const encoded = normalized.split('/').map(encodeURIComponent).join('/');
  return `${API_BASE}/api/media/${encoded}`;
}

function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Delay aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Delay aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),

  getGroupSummaries: () => request<{ groups: GroupSummary[] }>('/api/groups'),

  async getGroups(): Promise<QuizGroup[]> {
    const payload = await api.getGroupSummaries();
    const fullGroups = await Promise.all(
      payload.groups.map((group) => api.getGroup(group.id))
    );
    return fullGroups;
  },

  async getAccounts(): Promise<AccountProfilePublic[]> {
    const payload = await request<{ accounts: AccountProfilePublic[] }>('/api/accounts');
    return payload.accounts;
  },

  async getCurrentAccount(): Promise<AccountProfilePublic> {
    const payload = await request<{ account: AccountProfilePublic }>('/api/accounts/current');
    return payload.account;
  },

  async setCurrentAccount(profileId: string): Promise<AccountProfilePublic> {
    const payload = await request<{ account: AccountProfilePublic }>('/api/accounts/current', {
      method: 'POST',
      body: JSON.stringify({ profile_id: profileId }),
    });
    return payload.account;
  },

  async createAccount(_options: unknown): Promise<AccountProfilePublic> {
    throw new Error(ACCOUNT_MANAGEMENT_DISABLED);
  },

  async updateAccount(
    _profileId: string,
    _options: unknown,
  ): Promise<AccountProfilePublic> {
    throw new Error(ACCOUNT_MANAGEMENT_DISABLED);
  },

  deleteAccount: (profileId: string) =>
    request<{ active_account: AccountProfilePublic | null; deleted: boolean; id: string }>(
      `/api/accounts/${encodeURIComponent(profileId)}/delete`,
      { method: 'POST' },
    ),

  async enableAccount(profileId: string): Promise<AccountProfilePublic> {
    const payload = await request<{ account: AccountProfilePublic }>(
      `/api/accounts/${encodeURIComponent(profileId)}/enable`,
      { method: 'POST' },
    );
    return payload.account;
  },

  async disableAccount(profileId: string): Promise<AccountProfilePublic> {
    const payload = await request<{ account: AccountProfilePublic }>(
      `/api/accounts/${encodeURIComponent(profileId)}/disable`,
      { method: 'POST' },
    );
    return payload.account;
  },

  async getRuns(): Promise<RunStatusSnapshot[]> {
    const payload = await request<{ runs: RunStatusSnapshot[] }>('/api/runs');
    return payload.runs;
  },

  getActiveRun: () => request<ActiveRunResponse>('/api/runs/active'),

  getRun: (runId: string) =>
    request<RunStatusSnapshot>(`/api/runs/${encodeURIComponent(runId)}`),

  pauseRun: (runId: string) =>
    request<RunStatusSnapshot>(`/api/runs/${encodeURIComponent(runId)}/pause`, {
      method: 'POST',
    }),

  resumeRun: (runId: string) =>
    request<{ job_id: string }>(`/api/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
    }),

  continueRun: (
    runId: string,
    questionIndex: number,
    options: {
      confirmSkipForward?: boolean;
      contextSendMode?: 'once' | 'per-question';
      shuffleOptions?: boolean;
      speed?: 'normal' | 'fast';
    } = {},
  ) =>
    request<{ job_id: string }>(`/api/runs/${encodeURIComponent(runId)}/continue`, {
      method: 'POST',
      body: JSON.stringify({
        confirm_skip_forward: options.confirmSkipForward ?? false,
        context_send_mode: options.contextSendMode,
        question_index: questionIndex,
        shuffle_options: options.shuffleOptions,
        speed: options.speed,
      }),
    }),

  stopRun: (runId: string) =>
    request<RunStatusSnapshot>(`/api/runs/${encodeURIComponent(runId)}/stop`, {
      method: 'POST',
    }),

  updateRunAutoResume: (runId: string, options: { delaySeconds: number; enabled: boolean }) =>
    request<RunStatusSnapshot>(`/api/runs/${encodeURIComponent(runId)}/auto-resume`, {
      method: 'PATCH',
      body: JSON.stringify({
        delay_seconds: options.delaySeconds,
        enabled: options.enabled,
      }),
    }),

  getSettings: () => request<SettingsResponse>('/api/settings'),

  updateEtaSettings: (options: { bot_response_seconds: number }) =>
    request<{ eta: { bot_response_seconds: number } }>('/api/settings/eta', {
      method: 'PATCH',
      body: JSON.stringify(options),
    }),

  startTelegramLogin: (profileId: string, options: { forceSms?: boolean } = {}) =>
    request<TelegramLoginStartResponse>('/api/auth/telegram/start', {
      method: 'POST',
      body: JSON.stringify({
        force_sms: options.forceSms ?? false,
        profile_id: profileId,
      }),
    }),

  submitTelegramCode: (loginId: string, code: string) =>
    request<TelegramLoginCodeResponse>('/api/auth/telegram/code', {
      method: 'POST',
      body: JSON.stringify({ login_id: loginId, code }),
    }),

  submitTelegramPassword: (loginId: string, password: string) =>
    request<TelegramLoginAuthorizedResponse>('/api/auth/telegram/password', {
      method: 'POST',
      body: JSON.stringify({ login_id: loginId, password }),
    }),

  getTelegramLoginStatus: (loginId: string) =>
    request<TelegramLoginStatusResponse>(
      `/api/auth/telegram/${encodeURIComponent(loginId)}`
    ),

  cancelTelegramLogin: (loginId: string) =>
    request<{ ok: boolean }>(`/api/auth/telegram/${encodeURIComponent(loginId)}`, {
      method: 'DELETE',
    }),

  getGroup: (groupId: string) => request<QuizGroup>(`/api/groups/${encodeURIComponent(groupId)}`),

  uploadMedia(file: File) {
    const form = new FormData();
    form.append('file', file);
    return request<{ path: string; filename: string; saved_path: string }>('/api/media/upload', {
      method: 'POST',
      body: form,
    });
  },

  saveGroup: (group: QuizGroup) =>
    request<QuizGroup>(`/api/groups/${encodeURIComponent(group.id)}`, {
      method: 'PUT',
      body: JSON.stringify(group),
    }),

  archiveGroup: (groupId: string) =>
    request<{ id: string; archived: boolean; path: string }>(`/api/groups/${encodeURIComponent(groupId)}/archive`, {
      method: 'POST',
    }),

  deleteGroup: (groupId: string) =>
    request<{ id: string; deleted: boolean }>(`/api/groups/${encodeURIComponent(groupId)}/delete`, {
      method: 'POST',
    }),

  async createManualQuiz(title: string, workspaceDir: string, description = ''): Promise<QuizGroup> {
    const payload = await request<{ group: QuizGroup }>('/api/groups/manual', {
      method: 'POST',
      body: JSON.stringify({
        description,
        title,
        workspace_dir: workspaceDir,
      }),
    });
    return payload.group;
  },

  createQuizFromDocx(file: File, title: string, description: string, workspaceDir: string, useAiParsing = false) {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('description', description);
    form.append('workspace_dir', workspaceDir);
    form.append('use_ai', String(useAiParsing));
    return request<{ job_id: string }>('/api/jobs/create-from-docx', {
      method: 'POST',
      body: form,
    });
  },

  async importQuizJson(file: File, title: string, description: string, workspaceDir: string): Promise<QuizGroup> {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('description', description);
    form.append('workspace_dir', workspaceDir);
    const payload = await request<{ group: QuizGroup }>('/api/groups/import-json', {
      method: 'POST',
      body: form,
    });
    return payload.group;
  },

  validateGroup(groupId: string, strict: boolean) {
    return request<{ job_id: string }>('/api/jobs/validate', {
      method: 'POST',
      body: JSON.stringify({ group_id: groupId, strict }),
    });
  },

  uploadGroup(options: {
    group_id: string;
    name: string;
    speed: 'normal' | 'fast';
    context_send_mode: 'once' | 'per-question';
    shuffle_options: boolean;
    start_from?: number;
  }) {
    return request<{ job_id: string }>('/api/jobs/upload', {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  cancelJob(jobId: string) {
    return request<{ ok: boolean }>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
  },

  getJob(jobId: string) {
    return request<JobSnapshot>(`/api/jobs/${encodeURIComponent(jobId)}`);
  },

  subscribeJob(jobId: string, onEvent: (event: JobEvent) => void, onError: (error: Event) => void) {
    const source = new EventSource(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/events`);
    source.onmessage = (message) => onEvent(JSON.parse(message.data) as JobEvent);
    source.onerror = onError;
    return source;
  },

  async waitForJob(jobId: string, options: WaitForJobOptions = {}): Promise<JobSnapshot> {
    const { signal, timeoutMs, pollMs = 300 } = options;
    const deadline = timeoutMs && timeoutMs > 0 ? Date.now() + timeoutMs : null;
    for (;;) {
      if (signal?.aborted) throw new DOMException('waitForJob aborted', 'AbortError');
      const snapshot = await api.getJob(jobId);
      if (snapshot.status !== 'running') return snapshot;
      if (deadline !== null && Date.now() >= deadline) {
        throw new DOMException('waitForJob timed out', 'TimeoutError');
      }
      await abortableDelay(pollMs, signal);
    }
  },
};
