import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ApiError, authenticate, SESSION_COOKIE } from "@/lib/server-api";

export async function POST(request: Request) {
  try {
    const payload = await request.json();
    const result = await authenticate("login", payload);
    (await cookies()).set(SESSION_COOKIE, result.access_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: result.expires_in,
    });
    return NextResponse.json({ user: result.user });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 500;
    const detail = error instanceof Error ? error.message : "เข้าสู่ระบบไม่สำเร็จ";
    return NextResponse.json({ detail }, { status });
  }
}

