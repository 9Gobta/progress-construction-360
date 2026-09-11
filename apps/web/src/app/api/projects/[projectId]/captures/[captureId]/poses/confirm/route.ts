import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(
  request: Request,
  context: { params: Promise<{ projectId: string; captureId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId } = await context.params;
  const { floor_id: floorId } = await request.json();
  try {
    const result = await apiRequest(
      `/projects/${projectId}/captures/${captureId}/poses/confirm?floor_id=${encodeURIComponent(floorId)}`,
      { method: "POST", token },
    );
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "ยืนยัน Virtual Tour ไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
