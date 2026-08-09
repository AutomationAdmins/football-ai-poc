import MatchDetail from './match-detail';

export const dynamic = 'force-dynamic';

async function getInsights() {
  const baseUrl = process.env.BACKEND_API_URL ?? 'http://localhost:8000';
  const response = await fetch(`${baseUrl}/api/insights`, { cache: 'no-store' });
  if (!response.ok) return [];
  return response.json();
}

export default async function MatchPage({ params }: { params: Promise<{ fixtureId: string }> }) {
  const { fixtureId } = await params;
  const allInsights = await getInsights();
  const matchInsights = allInsights.filter((i: any) => i.fixture_id === decodeURIComponent(fixtureId));

  return <MatchDetail fixtureId={decodeURIComponent(fixtureId)} initialInsights={matchInsights} />;
}
