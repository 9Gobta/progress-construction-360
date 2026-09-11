import { NextResponse } from "next/server";

import { apiFetch, ApiError, getSessionToken } from "@/lib/server-api";

export async function POST(request: Request, context: { params: Promise<{ projectId: string; noteId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, noteId } = await context.params;
  try {
    const response = await apiFetch(`/projects/${projectId}/field-notes/${noteId}/attachments`, {
      method: "POST", token, body: await request.formData(),
    });
    const body = await response.json().catch(() => ({ detail: "แนบไฟล์ไม่สำเร็จ" }));
    return NextResponse.json(body, { status: response.status });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "แนบไฟล์ไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
