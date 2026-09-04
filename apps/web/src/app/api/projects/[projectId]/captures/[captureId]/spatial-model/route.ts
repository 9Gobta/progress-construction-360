import { NextResponse } from "next/server";

import { apiFetch, ApiError, getSessionToken } from "@/lib/server-api";

export async function GET(
  _request: Request,
  context: { params: Promise<{ projectId: string; captureId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, captureId } = await context.params;
  try {
    const upstream = await apiFetch(
      `/projects/${projectId}/captures/${captureId}/spatial-model`,
      { token, headers: { Accept: "application/json" } },
    );
    if (!upstream.ok || !upstream.body) {
      return NextResponse.json(
        { detail: "Capture นี้ยังไม่มีโมเดลสามมิติ" },
        { status: upstream.status || 502 },
      );
    }
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "private, max-age=300",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปิดโมเดลสามมิติไม่สำเร็จ" },
      { status },
    );
  }
}
