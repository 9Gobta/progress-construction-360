import { access, readFile } from "node:fs/promises";
import path from "node:path";

const allowedFiles = new Set(["web-ifc.wasm", "web-ifc-mt.wasm"]);

export const runtime = "nodejs";

export async function GET(_: Request, { params }: { params: Promise<{ filename: string }> }) {
  const { filename } = await params;
  if (!allowedFiles.has(filename)) return new Response("Not found", { status: 404 });

  const candidates = [
    path.resolve(process.cwd(), "node_modules", "web-ifc", filename),
    path.resolve(process.cwd(), "..", "..", "node_modules", "web-ifc", filename),
  ];
  let wasmPath: string | null = null;
  for (const candidate of candidates) {
    try {
      await access(candidate);
      wasmPath = candidate;
      break;
    } catch {
      // Try the monorepo-hoisted dependency location next.
    }
  }
  if (!wasmPath) return new Response("web-ifc runtime not installed", { status: 503 });
  const contents = await readFile(/* turbopackIgnore: true */ wasmPath);
  return new Response(contents, {
    headers: {
      "Content-Type": "application/wasm",
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
