import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(request: Request, context: { params: Promise<{ projectId: string; mediaId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, mediaId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/media/${mediaId}/multipart/complete`, {
      method: "POST",
      token,
      body: JSON.stringify(await request.json()),
    }));
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json({ detail: error instanceof Error ? error.message : "ปิด Upload ไม่สำเร็จ" }, { status });
  }
}
