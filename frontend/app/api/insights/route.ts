import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  const backendUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';
  const response = await fetch(`${backendUrl}/api/insights`, {
    cache: 'no-store',
  });

  if (!response.ok) {
    return NextResponse.json([], { status: 200 });
  }

  const data = await response.json();
  return NextResponse.json(data, { status: 200 });
}
