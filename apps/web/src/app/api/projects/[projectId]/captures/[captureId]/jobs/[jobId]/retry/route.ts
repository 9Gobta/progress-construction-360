import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(_request: Request, context: { params: Promise<{ projectId: string; captureId: string; jobId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId, jobId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/captures/${captureId}/jobs/${jobId}/retry`, { method: "POST", token }));
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json({ detail: error instanceof Error ? error.message : "Retry ไม่สำเร็จ" }, { status });
  }
}
