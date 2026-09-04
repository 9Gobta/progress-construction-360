import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function PUT(
  request: Request,
  context: { params: Promise<{ projectId: string; captureId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId } = await context.params;
  try {
    const result = await apiRequest(`/projects/${projectId}/captures/${captureId}/slab-progress`, {
      method: "PUT", token, body: JSON.stringify(await request.json()),
    });
    return NextResponse.json(result);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json({ detail: error instanceof Error ? error.message : "บันทึก Progress พื้นไม่สำเร็จ" }, { status });
  }
}
