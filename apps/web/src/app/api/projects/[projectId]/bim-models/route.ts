import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken, proxyBimModelDownloads } from "@/lib/server-api";
import type { BimModel, BimModelList } from "@/lib/types";

export const runtime = "nodejs";

function errorResponse(error: unknown) {
  if (error instanceof ApiError) {
    return NextResponse.json({ detail: error.message }, { status: error.status });
  }
  return NextResponse.json({ detail: "ไม่สามารถเชื่อมต่อบริการ BIM ได้" }, { status: 500 });
}

export async function GET(_: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await params;
  try {
    const models = await apiRequest<BimModelList>(`/projects/${projectId}/bim-models`, { token });
    return NextResponse.json(proxyBimModelDownloads(projectId, models));
  } catch (error) {
    return errorResponse(error);
  }
}

export async function POST(request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId } = await params;
  try {
    const formData = await request.formData();
    return NextResponse.json(
      await apiRequest<BimModel>(`/projects/${projectId}/bim-models`, {
        method: "POST",
        body: formData,
        token,
      }),
      { status: 201 },
    );
  } catch (error) {
    return errorResponse(error);
  }
}
