import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

type Context = { params: Promise<{ projectId: string }> };

export async function PATCH(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  const body = await request.json();
  try {
    const project = await apiRequest(`/projects/${projectId}/scope`, {
      method: "PATCH",
      token,
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    });
    return NextResponse.json(project);
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "บันทึกขอบเขตโครงการไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}

export async function DELETE(_request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  try {
    await apiRequest(`/projects/${projectId}`, { method: "DELETE", token });
    return NextResponse.json({ ok: true });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "ลบโครงการไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
