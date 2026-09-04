import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/server-api";

export async function POST(request: Request) {
  (await cookies()).delete(SESSION_COOKIE);
  return NextResponse.redirect(new URL("/", request.url), 303);
}

