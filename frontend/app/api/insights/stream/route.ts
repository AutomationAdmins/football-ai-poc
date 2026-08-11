import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * SSE proxy — forwards the backend's /api/insights/stream to the frontend.
 * Falls back gracefully if the backend stream is unavailable.
 */
export async function GET(_req: NextRequest) {
  const backendUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';

  try {
    const upstream = await fetch(`${backendUrl}/api/insights/stream`, {
      cache: 'no-store',
      headers: { Accept: 'text/event-stream' },
    });

    if (!upstream.ok || !upstream.body) {
      return new Response('data: []\n\n', {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
      });
    }

    return new Response(upstream.body as ReadableStream, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch {
    // Backend unreachable — return an empty SSE so the client doesn't error-loop
    return new Response('data: []\n\n', {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    });
  }
}
