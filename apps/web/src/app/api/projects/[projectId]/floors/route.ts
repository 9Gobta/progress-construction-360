import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  try {
    const floor = await apiRequest(`/projects/${projectId}/floors`, {
      method: "POST",
      token,
      body: JSON.stringify(await request.json()),
    });
    return NextResponse.json(floor, { status: 201 });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json({ detail: error instanceof Error ? error.message : "เพิ่มชั้นไม่สำเร็จ" }, { status });
  }
}
