import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

function failure(error: unknown) {
  const status = error instanceof ApiError ? error.status : 500;
  return NextResponse.json({ detail: error instanceof Error ? error.message : "ตรวจ Upload ไม่สำเร็จ" }, { status });
}

export async function GET(_request: Request, context: { params: Promise<{ projectId: string; mediaId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, mediaId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/media/${mediaId}/multipart`, { token }));
  } catch (error) {
    return failure(error);
  }
}
