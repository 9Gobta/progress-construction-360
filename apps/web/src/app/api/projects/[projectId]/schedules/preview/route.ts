import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

function failure(error: unknown) {
  const status = error instanceof ApiError ? error.status : 500;
  return NextResponse.json(
    { detail: error instanceof Error ? error.message : "ไม่สามารถตรวจไฟล์ได้" },
    { status },
  );
}

export async function POST(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  try {
    const data = await apiRequest(`/projects/${projectId}/schedules/preview`, {
      method: "POST",
      token,
      body: await request.formData(),
    });
    return NextResponse.json(data);
  } catch (error) {
    return failure(error);
  }
}
