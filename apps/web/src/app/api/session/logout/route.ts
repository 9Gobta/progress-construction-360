import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/server-api";

export async function POST(request: Request) {
  (await cookies()).delete(SESSION_COOKIE);
  // Behind Cloudflare, request.url can contain the internal bind host
  // (0.0.0.0). The browser Origin retains the public tunnel host.
  const browserOrigin = request.headers.get("origin");
  const redirectBase =
    browserOrigin && /^https?:\/\//i.test(browserOrigin)
      ? browserOrigin
      : request.url;
  return NextResponse.redirect(new URL("/", redirectBase), 303);
}
