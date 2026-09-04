import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ projectId: string; captureId: string; poseId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId, poseId } = await context.params;
  try {
    const result = await apiRequest(
      `/projects/${projectId}/captures/${captureId}/poses/${poseId}`,
      { method: "PATCH", token, body: JSON.stringify(await request.json()) },
    );
    return NextResponse.json(result);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "แก้ Camera Pose ไม่สำเร็จ" },
      { status },
    );
  }
}
