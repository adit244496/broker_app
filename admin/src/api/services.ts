// One function per admin API. Pages import from here only.

import type {
  AdminSession,
  BrokerStatus,
  BrokerWithStats,
  EmailSettings,
  EmailSettingsInput,
  Enquiry,
  EnquiryFilters,
  Hod,
  LeadField,
  AccountField,
  AccountForm,
  LeadForm,
  Overview,
  MediaKind,
  ProjectAccess,
  ProjectMedia,
  ProjectRef,
  ProjectVideo,
  ProjectWithAccess,
} from '@/types';
import { env, request } from './client';
import { endpoints } from './endpoints';
import * as map from './mappers';
import { mock } from './mock';

type ListResponse = { records: Record<string, any>[] };

export const authApi = {
  async login(email: string, password: string): Promise<AdminSession> {
    if (env.useMock) return mock.login(email, password);
    const res = await request<{ token: string; user: Record<string, any> }>(endpoints.login(), {
      method: 'POST',
      body: { email: email.trim(), password },
      auth: false,
    });
    return {
      token: res.token,
      user: { id: res.user.Id, name: res.user.Name, email: res.user.Email, role: res.user.Role === 'hod' ? 'hod' : 'admin' },
    };
  },
  restore(session: AdminSession) {
    if (env.useMock) mock.restore(session);
  },
  /** Your own password (admins and HODs); other sessions are signed out. */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    if (env.useMock) return mock.changePassword(currentPassword, newPassword);
    await request(endpoints.changePassword(), { method: 'POST', body: { currentPassword, newPassword } });
  },
  /** Ends the session on the server too. Call before clearing the stored token. */
  logout() {
    if (env.useMock) return mock.logout();
    request(endpoints.logout(), { method: 'POST' }).catch(() => {});
  },
};

export const overviewApi = {
  async get(from?: string): Promise<Overview> {
    if (env.useMock) return mock.overview(from);
    return map.overviewFromSf(await request(endpoints.overview(), { query: { from } }));
  },
};

export const brokerApi = {
  /** `from` limits the performance stats to enquiries created on or after that date. */
  async list(q: { search?: string; status?: BrokerStatus; from?: string } = {}): Promise<BrokerWithStats[]> {
    if (env.useMock) return mock.listBrokers(q);
    const res = await request<ListResponse>(endpoints.listBrokers(), { query: q });
    return res.records.map(map.brokerWithStatsFromSf);
  },
  async get(id: string): Promise<BrokerWithStats> {
    if (env.useMock) return mock.getBroker(id);
    return map.brokerWithStatsFromSf(await request(endpoints.getBroker(id)));
  },
  /** Creates the account in Salesforce. `syncError` is set when Salesforce didn't take it (retry with `sync`). */
  /** `approvalStage: 'admin'` = an HOD's approval: it now waits for an admin's final approval. */
  async approve(id: string): Promise<{ syncError?: string; approvalStage?: 'admin' }> {
    if (env.useMock) return mock.approveBroker(id);
    const res = await request<{ syncError?: string; approvalStage?: 'admin' }>(endpoints.approveBroker(id), { method: 'POST' });
    return { syncError: res.syncError, approvalStage: res.approvalStage };
  },
  /** Retries creating an approved registration in Salesforce. */
  async sync(id: string) {
    if (env.useMock) return mock.syncBroker(id);
    await request(endpoints.syncBroker(id), { method: 'POST' });
  },
  async reject(id: string, reason: string) {
    if (env.useMock) return mock.rejectBroker(id, reason);
    await request(endpoints.rejectBroker(id), { method: 'POST', body: { reason } });
  },
};

export const enquiryApi = {
  async list(filters: EnquiryFilters = {}): Promise<Enquiry[]> {
    if (env.useMock) return mock.listEnquiries(filters);
    const res = await request<ListResponse>(endpoints.listEnquiries(), { query: { ...filters } });
    return res.records.map(map.enquiryFromSf);
  },
};

export const settingsApi = {
  async getEmail(): Promise<EmailSettings> {
    if (env.useMock) return mock.getEmailSettings();
    return request<EmailSettings>(endpoints.emailSettings());
  },
  async saveEmail(input: EmailSettingsInput): Promise<EmailSettings> {
    if (env.useMock) return mock.saveEmailSettings(input);
    return request<EmailSettings>(endpoints.emailSettings(), { method: 'PUT', body: input });
  },
  async getAccountForm(): Promise<AccountForm> {
    if (env.useMock) return mock.getAccountForm();
    return request<AccountForm>(endpoints.accountForm());
  },
  async saveAccountForm(fields: AccountField[]): Promise<AccountForm> {
    if (env.useMock) return mock.saveAccountForm(fields);
    return request<AccountForm>(endpoints.accountForm(), { method: 'PUT', body: { fields } });
  },
  async resetAccountForm(): Promise<AccountForm> {
    if (env.useMock) return mock.resetAccountForm();
    return request<AccountForm>(endpoints.resetAccountForm(), { method: 'POST' });
  },
  async getLeadForm(): Promise<LeadForm> {
    if (env.useMock) return mock.getLeadForm();
    return request<LeadForm>(endpoints.leadForm());
  },
  async saveLeadForm(fields: LeadField[]): Promise<LeadForm> {
    if (env.useMock) return mock.saveLeadForm(fields);
    return request<LeadForm>(endpoints.leadForm(), { method: 'PUT', body: { fields } });
  },
  async resetLeadForm(): Promise<LeadForm> {
    if (env.useMock) return mock.resetLeadForm();
    return request<LeadForm>(endpoints.resetLeadForm(), { method: 'POST' });
  },
  async listHods(): Promise<Hod[]> {
    if (env.useMock) return mock.listHods();
    return (await request<{ records: Hod[] }>(endpoints.hods())).records;
  },
  /** `password` (optional) lets the HOD sign in to the portal too. */
  async addHod(name: string, email: string, password?: string): Promise<Hod> {
    if (env.useMock) return mock.addHod(name, email, password);
    return request<Hod>(endpoints.hods(), { method: 'POST', body: { name, email, password: password || undefined } });
  },
  async setHodPassword(id: number, password: string): Promise<void> {
    if (env.useMock) return mock.setHodPassword(id, password);
    await request(endpoints.hodPassword(id), { method: 'PUT', body: { password } });
  },
  async removeHod(id: number): Promise<void> {
    if (env.useMock) return mock.removeHod(id);
    await request(endpoints.hod(id), { method: 'DELETE' });
  },
  /** Sends a test email with the saved account; to the signed-in admin unless `to` is given. */
  async testEmail(to?: string): Promise<{ sent: boolean; to: string }> {
    if (env.useMock) return mock.testEmail(to);
    return request(endpoints.testEmail(), { method: 'POST', body: { to } });
  },
};

export const projectApi = {
  async list(): Promise<ProjectRef[]> {
    if (env.useMock) return mock.listProjects();
    const res = await request<ListResponse>(endpoints.listProjects());
    return res.records.map((r) => ({ id: r.Id, name: r.Name }));
  },
  /** Projects with who can see them in the broker app. */
  async listWithAccess(): Promise<ProjectWithAccess[]> {
    if (env.useMock) return mock.listProjectsWithAccess();
    const res = await request<ListResponse>(endpoints.listProjects());
    return res.records.map(map.projectWithAccessFromApi);
  },
  async uploadImage(id: string, kind: MediaKind, file: File): Promise<ProjectMedia> {
    if (env.useMock) return mock.uploadProjectImage(id, kind, file);
    const form = new FormData();
    form.append('file', file);
    const res = await request<{ media: Record<string, any> }>(endpoints.projectImage(id, kind), { method: 'PUT', body: form });
    return map.projectMediaFromApi(res.media);
  },
  async removeImage(id: string, kind: MediaKind): Promise<ProjectMedia> {
    if (env.useMock) return mock.removeProjectImage(id, kind);
    const res = await request<{ media: Record<string, any> }>(endpoints.projectImage(id, kind), { method: 'DELETE' });
    return map.projectMediaFromApi(res.media);
  },
  async setVideos(id: string, videos: Pick<ProjectVideo, 'id' | 'title' | 'url'>[]): Promise<ProjectMedia> {
    if (env.useMock) return mock.setProjectVideos(id, videos);
    const res = await request<{ media: Record<string, any> }>(endpoints.projectVideos(id), { method: 'PUT', body: { videos } });
    return map.projectMediaFromApi(res.media);
  },
  async setAccess(id: string, access: ProjectAccess): Promise<ProjectAccess> {
    if (env.useMock) return mock.setProjectAccess(id, access);
    const res = await request<{ access: ProjectAccess }>(endpoints.projectAccess(id), { method: 'PUT', body: access });
    return res.access;
  },
};
