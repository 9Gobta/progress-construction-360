import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

type Context = { params: Promise<{ projectId: string; memberId: string }> };

export async function PATCH(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, memberId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/members/${memberId}`, {
      method: "PATCH", token, body: JSON.stringify(await request.json()),
    }));
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปลี่ยนสิทธิ์ไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}

export async function DELETE(_request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, memberId } = await context.params;
  try {
    await apiRequest(`/projects/${projectId}/members/${memberId}`, { method: "DELETE", token });
    return NextResponse.json({ ok: true });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "นำสมาชิกออกไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
