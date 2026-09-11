import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(request: Request, context: { params: Promise<{ projectId: string; noteId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, noteId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/field-notes/${noteId}/comments`, {
      method: "POST", token, body: JSON.stringify(await request.json()),
    }), { status: 201 });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เพิ่มความคิดเห็นไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
