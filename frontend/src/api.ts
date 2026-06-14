import { JobEvent, JobSnapshot, QuizGroup, GroupSummary, SourceGroupSummary } from './types';

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (window.location.port === '3000' ? 'http://127.0.0.1:8000' : '');

export function mediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.replace(/\\/g, '/').replace(/^\/+/, '');
  const encoded = normalized.split('/').map(encodeURIComponent).join('/');
  return `${API_BASE}/api/media/${encoded}`;
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
  health: () => request<{ ok: boolean }>('/api/health'),

  async getGroups(): Promise<QuizGroup[]> {
    const payload = await request<{ groups: GroupSummary[] }>('/api/groups');
    const fullGroups = await Promise.all(
      payload.groups.map((group) => api.getGroup(group.id))
    );
    return fullGroups;
  },

  async getSourceGroups(): Promise<SourceGroupSummary[]> {
    const payload = await request<{ groups: SourceGroupSummary[] }>('/api/source-groups');
    return payload.groups;
  },

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

  parseDocx(file: File, title: string, description: string, workspaceDir: string) {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('description', description);
    form.append('workspace_dir', workspaceDir);
    return request<{ job_id: string }>('/api/jobs/parse-docx', {
      method: 'POST',
      body: form,
    });
  },

  generateAllGroups(options: {
    source_path?: string;
    output_dir?: string;
    groups?: string[];
    skip_existing?: boolean;
    model?: string;
    max_retries?: number;
    media_root?: string;
    style_examples?: number;
  }) {
    return request<{ job_id: string }>('/api/jobs/generate-all-groups', {
      method: 'POST',
      body: JSON.stringify(options),
    });
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
  }) {
    return request<{ job_id: string }>('/api/jobs/upload', {
      method: 'POST',
      body: JSON.stringify(options),
    });
  },

  uploadQueue(options: {
    items: Array<{ group_id: string; name?: string }>;
    speed: 'normal' | 'fast';
    context_send_mode: 'once' | 'per-question';
    shuffle_options: boolean;
  }) {
    return request<{ job_id: string }>('/api/jobs/upload-queue', {
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

  async waitForJob(jobId: string): Promise<JobSnapshot> {
    for (;;) {
      const snapshot = await api.getJob(jobId);
      if (snapshot.status !== 'running') return snapshot;
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
  },
};
