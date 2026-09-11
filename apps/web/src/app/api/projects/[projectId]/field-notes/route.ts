import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

type Context = { params: Promise<{ projectId: string }> };

export async function GET(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  const query = new URL(request.url).search;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/field-notes${query}`, { token }));
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "โหลดบันทึกหน้างานไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}

export async function POST(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await context.params;
  try {
    return NextResponse.json(await apiRequest(`/projects/${projectId}/field-notes`, {
      method: "POST", token, body: JSON.stringify(await request.json()),
    }), { status: 201 });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "สร้างบันทึกหน้างานไม่สำเร็จ" },
      { status: error instanceof ApiError ? error.status : 500 },
    );
  }
}
