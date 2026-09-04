import { NextResponse } from "next/server";

import { apiRequest, ApiError, getSessionToken } from "@/lib/server-api";

type Context = { params: Promise<{ projectId: string; floorId: string }> };

export async function GET(_: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, floorId } = await context.params;
  try {
    const result = await apiRequest<{ url: string }>(
      `/projects/${projectId}/floors/${floorId}/plan-url`,
      { token },
    );
    const image = await fetch(result.url, { cache: "no-store" });
    if (!image.ok) throw new Error("อ่านภาพแปลนไม่สำเร็จ");
    return new Response(await image.arrayBuffer(), {
      status: 200,
      headers: {
        "Content-Type": image.headers.get("Content-Type") ?? "image/png",
        "Cache-Control": "no-store, max-age=0",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปิดแปลนไม่สำเร็จ" },
      { status },
    );
  }
}

export async function POST(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, floorId } = await context.params;
  try {
    const result = await apiRequest(`/projects/${projectId}/floors/${floorId}/plan`, {
      method: "POST",
      token,
      body: await request.formData(),
    });
    return NextResponse.json(result);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "อัปโหลดแปลนไม่สำเร็จ" },
      { status },
    );
  }
}

export async function PATCH(request: Request, context: Context) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ detail: "กรุณาเข้าสู่ระบบ" }, { status: 401 });
  const { projectId, floorId } = await context.params;
  try {
    const result = await apiRequest(`/projects/${projectId}/floors/${floorId}/plan`, {
      method: "PATCH",
      token,
      body: JSON.stringify(await request.json()),
    });
    return NextResponse.json(result);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "เปลี่ยนหน้าแปลนไม่สำเร็จ" },
      { status },
    );
  }
}
