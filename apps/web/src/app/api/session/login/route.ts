import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ApiError, authenticate, SESSION_COOKIE } from "@/lib/server-api";

export async function POST(request: Request) {
  try {
    const payload = await request.json();
    const result = await authenticate("login", payload);
    const forwardedProtocol = request.headers
      .get("x-forwarded-proto")
      ?.split(",")[0]
      ?.trim();
    const usesHttps =
      forwardedProtocol === "https" || new URL(request.url).protocol === "https:";
    (await cookies()).set(SESSION_COOKIE, result.access_token, {
      httpOnly: true,
      sameSite: "lax",
      // Cloudflare terminates HTTPS before forwarding to the local Next server.
      // Deriving this per request keeps the tunnel cookie secure while allowing
      // the same production build to work on http://localhost during site work.
      secure: usesHttps,
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
