import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ApiError, authenticate, SESSION_COOKIE } from "@/lib/server-api";

export async function POST(request: Request) {
  try {
    const payload = await request.json();
    const result = await authenticate("register", payload);
    const forwardedProtocol = request.headers
      .get("x-forwarded-proto")
      ?.split(",")[0]
      ?.trim();
    const usesHttps =
      forwardedProtocol === "https" || new URL(request.url).protocol === "https:";
    (await cookies()).set(SESSION_COOKIE, result.access_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: usesHttps,
      path: "/",
      maxAge: result.expires_in,
    });
    return NextResponse.json({ user: result.user }, { status: 201 });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    const detail = error instanceof Error ? error.message : "สร้างบัญชีไม่สำเร็จ";
    return NextResponse.json({ detail }, { status });
  }
}
