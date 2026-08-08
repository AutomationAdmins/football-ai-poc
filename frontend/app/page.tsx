import DashboardClient from './dashboard-client';

export const dynamic = 'force-dynamic';

async function getInsights() {
  const baseUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';
  const response = await fetch(`${baseUrl}/api/insights`, {
    cache: 'no-store',
  });

  if (!response.ok) {
    return [];
  }

  return response.json();
}

export default async function Page() {
  const insights = await getInsights();

  return <DashboardClient initialInsights={insights} />;
}
