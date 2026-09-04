import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ projectId: string; captureId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId } = await context.params;
  try {
    await apiRequest(`/projects/${projectId}/captures/${captureId}`, {
      method: "DELETE",
      token,
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "ลบ Capture ไม่สำเร็จ" },
      { status },
    );
  }
}
