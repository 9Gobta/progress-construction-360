import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function PUT(request: Request, context: { params: Promise<{ projectId: string; captureId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(
      `/projects/${projectId}/captures/${captureId}/work-progress`,
      { method: "PUT", token, body: JSON.stringify(await request.json()) },
    ));
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "บันทึก Progress ไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
