import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";
import type { Project } from "@/lib/types";

function errorResponse(error: unknown) {
  const status = error instanceof ApiError ? error.status : 500;
  const detail = error instanceof Error ? error.message : "Backend request failed";
  return NextResponse.json({ detail }, { status });
}

export async function GET() {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  try {
    return NextResponse.json(await apiRequest<Project[]>("/projects", { token }));
  } catch (error) {
    return errorResponse(error);
  }
}

export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  try {
    const payload = await request.json();
    const project = await apiRequest<Project>("/projects", {
      token,
      method: "POST",
      body: JSON.stringify(payload),
    });
    return NextResponse.json(project, { status: 201 });
  } catch (error) {
    return errorResponse(error);
  }
}

