import "server-only";

import { cookies } from "next/headers";

import type {
  Activity,
  BeamProgress,
  ColumnProgress,
  BeamSegment,
  BimModelList,
  Capture,
  CaptureDetail,
  Floor,
  FieldNote,
  HumanProgressEntry,
  Project,
  ProjectMember,
  ProgressComparison,
  ScheduleVersion,
  SlabProgress,
  StairProgress,
  StorageStatus,
  StructuralElement,
  TokenResponse,
  User,
  WorkProgress,
} from "@/lib/types";

export const SESSION_COOKIE = "progress_access_token";
// Keep this aligned with the local Uvicorn bind address. On Windows, Node may
// resolve `localhost` to IPv6 (::1), while Uvicorn is listening on 127.0.0.1.
const API_BASE_URL = process.env.API_SERVER_URL ?? "http://127.0.0.1:8000/api/v1";
const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

type ApiOptions = RequestInit & { token?: string };

export async function apiFetch(path: string, options: ApiOptions = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token) headers.set("Authorization", `Bearer ${options.token}`);

  return fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
}

export async function apiRequest<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  const response = await apiFetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.detail ?? "Backend request failed";
    throw new ApiError(response.status, typeof message === "string" ? message : JSON.stringify(message));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export async function authenticate(
  mode: "login" | "register",
  payload: Record<string, string>,
): Promise<TokenResponse> {
  return apiRequest<TokenResponse>(`/auth/${mode}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSessionToken(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

export async function getCurrentUser(): Promise<User | null> {
  const token = await getSessionToken();
  if (!token) return null;
  try {
    return await apiRequest<User>("/auth/me", { token });
  } catch {
    return null;
  }
}

export async function getProjects(): Promise<Project[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<Project[]>("/projects", { token });
}

export async function getProject(projectId: string): Promise<Project> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<Project>(`/projects/${projectId}`, { token });
}

export async function getBimModels(projectId: string): Promise<BimModelList> {
  const token = await getSessionToken();
  if (!token) return { active: null, versions: [] };
  const models = await apiRequest<BimModelList>(`/projects/${projectId}/bim-models`, { token });
  return proxyBimModelDownloads(projectId, models);
}

export function proxyBimModelDownloads(projectId: string, models: BimModelList): BimModelList {
  const rewrite = (model: BimModelList["versions"][number]) => ({
    ...model,
    download_url: `/api/projects/${encodeURIComponent(projectId)}/bim-models/${encodeURIComponent(model.id)}/file`,
  });
  const versions = models.versions.map(rewrite);
  const active = models.active
    ? versions.find((model) => model.id === models.active?.id) ?? rewrite(models.active)
    : null;
  return { active, versions };
}

export async function getProjectMembers(projectId: string): Promise<ProjectMember[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<ProjectMember[]>(`/projects/${projectId}/members`, { token });
}

export async function getFieldNotes(projectId: string, query = ""): Promise<FieldNote[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<FieldNote[]>(`/projects/${projectId}/field-notes${query ? `?${query}` : ""}`, { token });
}

export async function getSchedules(projectId: string): Promise<ScheduleVersion[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<ScheduleVersion[]>(`/projects/${projectId}/schedules`, { token });
}

export async function getActivities(projectId: string, scheduleId: string): Promise<Activity[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<Activity[]>(`/projects/${projectId}/schedules/${scheduleId}/activities`, { token });
}

export async function getHumanProgress(projectId: string): Promise<HumanProgressEntry[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<HumanProgressEntry[]>(`/projects/${projectId}/progress/manual`, { token });
}

export async function getProgressComparison(
  projectId: string,
  captureId: string,
): Promise<ProgressComparison> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<ProgressComparison>(
    `/projects/${projectId}/progress/comparison?capture_id=${encodeURIComponent(captureId)}`,
    { token },
  );
}

export async function getFloors(projectId: string): Promise<Floor[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<Floor[]>(`/projects/${projectId}/floors`, { token });
}

export async function getBeamSegments(projectId: string, floorId: string): Promise<BeamSegment[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<BeamSegment[]>(`/projects/${projectId}/floors/${floorId}/beam-segments`, { token });
}

export async function getStructuralElements(projectId: string, floorId: string): Promise<StructuralElement[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<StructuralElement[]>(`/projects/${projectId}/floors/${floorId}/structural-elements`, { token });
}

export async function getBeamProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<BeamProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<BeamProgress>(
    `/projects/${projectId}/captures/${captureId}/beam-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getColumnProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<ColumnProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<ColumnProgress>(
    `/projects/${projectId}/captures/${captureId}/column-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getSlabProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<SlabProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<SlabProgress>(
    `/projects/${projectId}/captures/${captureId}/slab-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getStairProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<StairProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<StairProgress>(
    `/projects/${projectId}/captures/${captureId}/stair-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getRoofProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<import("@/lib/types").RoofProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<import("@/lib/types").RoofProgress>(
    `/projects/${projectId}/captures/${captureId}/roof-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getWorkProgress(
  projectId: string,
  captureId: string,
  floorId: string,
): Promise<WorkProgress> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<WorkProgress>(
    `/projects/${projectId}/captures/${captureId}/work-progress?floor_id=${encodeURIComponent(floorId)}`,
    { token },
  );
}

export async function getCaptures(projectId: string): Promise<Capture[]> {
  const token = await getSessionToken();
  if (!token) return [];
  return apiRequest<Capture[]>(`/projects/${projectId}/captures`, { token });
}

export async function getStorageStatus(projectId: string): Promise<StorageStatus | null> {
  const token = await getSessionToken();
  if (!token) return null;
  try {
    return await apiRequest<StorageStatus>(`/projects/${projectId}/storage/status`, { token });
  } catch {
    return null;
  }
}

export async function getCaptureDetail(projectId: string, captureId: string): Promise<CaptureDetail> {
  const token = await getSessionToken();
  if (!token) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
  return apiRequest<CaptureDetail>(`/projects/${projectId}/captures/${captureId}`, { token });
}

export async function getApiHealth(): Promise<{ ok: boolean }> {
  try {
    const response = await fetch(`${API_ORIGIN}/health/live`, { cache: "no-store" });
    return { ok: response.ok };
  } catch {
    return { ok: false };
  }
}
