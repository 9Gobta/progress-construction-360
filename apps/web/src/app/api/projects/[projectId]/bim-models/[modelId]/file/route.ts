import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";
import type { BimModelList } from "@/lib/types";

export const runtime = "nodejs";

export async function GET(
  _request: Request,
  context: { params: Promise<{ projectId: string; modelId: string }> },
) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, modelId } = await context.params;
  try {
    // Fetch the authorized model list server-side, then stream the trusted
    // presigned storage URL through this same-origin route. Remote browsers
    // must never receive MinIO's localhost URL because that would point at the
    // reviewer's own computer.
    const models = await apiRequest<BimModelList>(`/projects/${projectId}/bim-models`, { token });
    const model = models.versions.find((candidate) => candidate.id === modelId);
    if (!model) return NextResponse.json({ detail: "ไม่พบโมเดล BIM" }, { status: 404 });
    const storageUrl = new URL(model.download_url);
    const upstream = await fetch(storageUrl, {
      cache: "no-store",
      headers: { Accept: "application/x-step, application/octet-stream" },
    });
    if (!upstream.ok || !upstream.body) {
      return NextResponse.json({ detail: "อ่านไฟล์ BIM ไม่สำเร็จ" }, { status: upstream.status || 502 });
    }
    const headers = new Headers({
      "Content-Type": upstream.headers.get("content-type") ?? "application/x-step",
      "Cache-Control": "private, no-store, max-age=0",
    });
    const contentLength = upstream.headers.get("content-length");
    if (contentLength) headers.set("Content-Length", contentLength);
    return new Response(upstream.body, { status: 200, headers });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปิดไฟล์ BIM ไม่สำเร็จ" },
      { status },
    );
  }
}
