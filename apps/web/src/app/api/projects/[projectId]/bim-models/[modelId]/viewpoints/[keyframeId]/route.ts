import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";
import type { BimViewpoint } from "@/lib/types";

export const runtime = "nodejs";

type Context = { params: Promise<{ projectId: string; modelId: string; keyframeId: string }> };

function errorResponse(error: unknown) {
  const status = error instanceof ApiError ? error.status : 500;
  return NextResponse.json(
    { detail: error instanceof Error ? error.message : "เชื่อมต่อมุมมอง BIM ไม่สำเร็จ" },
    { status },
  );
}

export async function GET(_request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, modelId, keyframeId } = await context.params;
  try {
    return NextResponse.json(await apiRequest<BimViewpoint | null>(
      `/projects/${projectId}/bim-models/${modelId}/viewpoints/${keyframeId}`,
      { token },
    ));
  } catch (error) {
    return errorResponse(error);
  }
}

export async function PUT(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, modelId, keyframeId } = await context.params;
  try {
    return NextResponse.json(await apiRequest<BimViewpoint>(
      `/projects/${projectId}/bim-models/${modelId}/viewpoints/${keyframeId}`,
      { method: "PUT", body: JSON.stringify(await request.json()), token },
    ));
  } catch (error) {
    return errorResponse(error);
  }
}
