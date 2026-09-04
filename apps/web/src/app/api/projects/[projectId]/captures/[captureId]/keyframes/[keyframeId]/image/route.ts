import { NextResponse } from "next/server";

import { apiFetch, ApiError, getSessionToken } from "@/lib/server-api";

export async function GET(
  _request: Request,
  context: {
    params: Promise<{ projectId: string; captureId: string; keyframeId: string }>;
  },
) {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  }
  const { projectId, captureId, keyframeId } = await context.params;
  try {
    // Ask for exactly one image. The former implementation downloaded the
    // complete Capture JSON for every hotspot click.
    const upstream = await apiFetch(
      `/projects/${projectId}/captures/${captureId}/keyframes/${keyframeId}/image`,
      { token, headers: { Accept: "image/jpeg" } },
    );
    if (!upstream.ok || !upstream.body) {
      return NextResponse.json(
        { detail: "อ่านไฟล์ภาพ 360 ไม่สำเร็จ" },
        { status: upstream.status || 502 },
      );
    }
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "image/jpeg",
        // The in-page neighbour cache handles speed. Avoid a stale 1920px
        // response after a legacy Capture is upgraded to a 4K tour image.
        "Cache-Control": "private, no-store, max-age=0",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปิดภาพ 360 ไม่สำเร็จ" },
      { status },
    );
  }
}
