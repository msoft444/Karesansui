import { NextRequest } from "next/server";

// Force dynamic so Next.js never statically optimizes or caches this handler.
export const dynamic = "force-dynamic";

/**
 * GET /api/stream/progress?run_id=<id>
 *
 * Proxies the FastAPI SSE endpoint to the browser.  This Route Handler
 * intentionally bypasses the next.config.js rewrite rule — Route Handlers
 * have higher priority than rewrites in Next.js App Router.  The rewrite
 * mechanism buffers the response body before forwarding it, which breaks
 * Server-Sent Events; piping the upstream ReadableStream through a Route
 * Handler avoids that buffering entirely.
 */
export async function GET(request: NextRequest) {
  const runId = request.nextUrl.searchParams.get("run_id");
  if (!runId) {
    return new Response("Missing run_id parameter", { status: 400 });
  }

  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8001";
  const backendUrl = `${apiBaseUrl}/stream/progress?run_id=${encodeURIComponent(runId)}`;

  let upstream: Response;
  try {
    upstream = await fetch(backendUrl, {
      cache: "no-store",
      headers: {
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
      },
    });
  } catch {
    return new Response("Failed to connect to backend stream", { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response("Backend stream unavailable", { status: 502 });
  }

  // Pipe the upstream ReadableStream directly to the client.  Passing the
  // body through a TransformStream ensures the runtime does not accumulate
  // the full response before flushing — every SSE frame is forwarded as soon
  // as it is received from the backend.
  const { readable, writable } = new TransformStream();
  upstream.body.pipeTo(writable).catch(() => {
    // Client disconnected before the stream ended — suppress the error.
  });

  return new Response(readable, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
