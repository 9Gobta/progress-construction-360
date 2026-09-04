import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/members`, {
      method: "POST", token, body: JSON.stringify(await request.json()),
    }), { status: 201 });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เพิ่มสมาชิกไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
