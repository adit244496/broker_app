// One function per Salesforce API. Screens import from here only.
// Read APIs return records as `{ records: [...] }` (list) or a single record;
// adjust the unwrapping below if the Salesforce team's response shape differs.

import { describeLoginId, isMobileId, type LoginId } from '@/auth/loginId';
import { env } from '@/config/env';
import type {
  Enquiry,
  AccountForm,
  RegistrationValues,
  LeadField,
  LeadValues,
  OtpRequestResult,
  PartnerLookup,
  RegistrationResult,
  Session,
} from '@/types/models';
import { request } from './client';
import { endpoints } from './endpoints';
import { mock } from './mock/mockData';
import * as map from './salesforce/mappers';

type ListResponse = { records: Record<string, any>[] };
type CreateResponse = { id: string; success?: boolean; record?: Record<string, any> };

// ---------- Auth (brokers log in with their registered mobile or email: a code, or a password) ----------

type LoginResponse = { token: string; user?: Record<string, any>; account?: Record<string, any> };
type OtpResponse = { channel?: 'sms' | 'whatsapp' | 'email'; maskedMobile?: string; maskedEmail?: string };

function sessionFrom(res: LoginResponse): Session {
  const user = res.user ? map.profileFromSf(res.user) : map.profileFromBroker(map.brokerFromSf(res.account ?? {}));
  return { token: res.token, user };
}

export const authApi = {
  /**
   * Step 1 of login: is this the mobile or email of a Channel Partner, and have they been added in
   * Salesforce yet? `pushToken` lets the backend refresh the token it will notify a pending broker on.
   */
  async check(id: LoginId, pushToken?: string): Promise<PartnerLookup> {
    if (env.useMock) return mock.check(id);
    const path = isMobileId(id) ? endpoints.checkMobile() : endpoints.checkEmail();
    return map.partnerLookupFromSf(await request(path, { method: 'POST', body: { ...id, pushToken }, auth: false }));
  },

  /** Sends a login code: by SMS or WhatsApp for a mobile (the admin decides), by email for an email. Refused unless active and added. */
  async requestOtp(id: LoginId): Promise<OtpRequestResult> {
    if (env.useMock) return mock.requestOtp(id);
    const res = await request<OtpResponse>(endpoints.requestOtp(), { method: 'POST', body: id, auth: false });
    return res.maskedMobile
      ? { channel: res.channel === 'whatsapp' ? 'whatsapp' : 'sms', masked: res.maskedMobile }
      : { channel: 'email', masked: res.maskedEmail ?? describeLoginId(id) };
  },

  async verifyOtp(id: LoginId, otp: string): Promise<Session> {
    if (env.useMock) return mock.verifyOtp(id, otp);
    return sessionFrom(await request<LoginResponse>(endpoints.verifyOtp(), { method: 'POST', body: { ...id, otp }, auth: false }));
  },

  async passwordLogin(id: LoginId, password: string): Promise<Session> {
    if (env.useMock) return mock.passwordLogin(id, password);
    return sessionFrom(
      await request<LoginResponse>(endpoints.passwordLogin(), { method: 'POST', body: { ...id, password }, auth: false }),
    );
  },

  /** Needs `currentPassword` only when changing a password from a password login. */
  async setPassword(newPassword: string, currentPassword?: string): Promise<void> {
    if (env.useMock) return mock.setPassword(newPassword, currentPassword);
    await request(endpoints.setPassword(), { method: 'POST', body: { newPassword, currentPassword } });
  },

  /** The registration form's fields, in order (managed by admins in the portal). */
  async getAccountForm(): Promise<AccountForm> {
    if (env.useMock) return mock.getAccountForm();
    return request<AccountForm>(endpoints.accountForm(), { auth: false });
  },

  /** Self-registration: waits for HOD/admin approval; the Salesforce account is created once approved. */
  async register(values: RegistrationValues, pushToken?: string): Promise<RegistrationResult> {
    if (env.useMock) return mock.register(values, pushToken);
    const res = await request<CreateResponse & { status?: RegistrationResult['status'] }>(endpoints.registerBroker(), {
      method: 'POST',
      body: { fields: values, pushToken },
      auth: false,
    });
    return { id: res.id, status: res.status ?? 'Pending Approval' };
  },

  restore(session: Session) {
    if (env.useMock) mock.restore(session);
  },

  /** Ends the session on the server too. Call before clearing the stored token. */
  logout() {
    if (env.useMock) return mock.logout();
    request(endpoints.logout(), { method: 'POST' }).catch(() => {});
  },
};

// ---------- Dashboard ----------

export const dashboardApi = {
  async getSummary() {
    if (env.useMock) return mock.dashboard();
    return map.dashboardFromSf(await request(endpoints.dashboardSummary()));
  },
};

// ---------- Enquiries ----------

export const enquiryApi = {
  async list(search?: string) {
    if (env.useMock) {
      const all = await mock.listEnquiries();
      return search ? all.filter((e) => matches(search, e.firstName, e.lastName, e.mobile, e.enquiryNumber)) : all;
    }
    const res = await request<ListResponse>(endpoints.listEnquiries(), { query: { search } });
    return res.records.map(map.enquiryFromSf);
  },

  async get(id: string) {
    if (env.useMock) return mock.getEnquiry(id);
    return map.enquiryFromSf(await request(endpoints.getEnquiry(id)));
  },

  /** Status timeline, sourced from Salesforce field history. */
  async statusHistory(id: string) {
    if (env.useMock) return mock.getEnquiryStatusHistory(id);
    const res = await request<ListResponse>(endpoints.getEnquiryStatusHistory(id));
    return res.records.map(map.statusEventFromSf);
  },

  /**
   * Submits the lead form's values (by field key). The backend checks them against the admin-defined
   * form, maps them to Salesforce Lead fields and adds the logged-in broker's Account Id.
   */
  async create(values: LeadValues): Promise<Enquiry> {
    if (env.useMock) return mock.createEnquiry(values);
    const res = await request<CreateResponse>(endpoints.createEnquiry(), { method: 'POST', body: { fields: values } });
    if (!res.record) throw new Error('The lead was created but could not be loaded. Pull to refresh your leads.');
    return map.enquiryFromSf(res.record);
  },
};

export const leadFormApi = {
  /** The fields to show on "create lead", in order, as set by admins in the portal. */
  async get(): Promise<LeadField[]> {
    if (env.useMock) return mock.getLeadForm();
    return (await request<{ fields: LeadField[] }>(endpoints.leadForm())).fields;
  },
};

// ---------- Projects / Brochures ----------

export const projectApi = {
  async list() {
    if (env.useMock) return mock.listProjects();
    const res = await request<ListResponse>(endpoints.listProjects());
    return res.records.map(map.projectFromSf);
  },

  async get(id: string) {
    if (env.useMock) return mock.getProject(id);
    return map.projectFromSf(await request(endpoints.getProject(id)));
  },
};

// ---------- Profile ----------

export const profileApi = {
  async get() {
    if (env.useMock) return mock.getProfile();
    return map.profileFromSf(await request(endpoints.getProfile()));
  },
};

function matches(q: string, ...fields: (string | undefined)[]) {
  const needle = q.trim().toLowerCase();
  return fields.some((f) => f?.toLowerCase().includes(needle));
}
