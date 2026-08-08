import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  context: { params: Promise<{ fixtureId: string; insightId: string }> },
) {
  const { fixtureId, insightId } = await context.params;
  const { action } = (await request.json().catch(() => ({}))) as { action?: 'approve' | 'reject' };

  if (action !== 'approve' && action !== 'reject') {
    return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
  }

  const backendUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';
  const response = await fetch(`${backendUrl}/${action}/${fixtureId}/${insightId}`, {
    method: 'POST',
  });

  if (!response.ok) {
    return NextResponse.json({ error: 'Backend decision failed' }, { status: 502 });
  }

  const data = await response.json();
  return NextResponse.json(data, { status: 200 });
}
