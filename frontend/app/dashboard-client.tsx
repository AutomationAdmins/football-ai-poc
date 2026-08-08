'use client';

import { useMemo, useState, useTransition } from 'react';

type InsightStat = {
  category: string;
  line: string;
};

type InsightItem = {
  id: string;
  fixture_id: string;
  lead_story?: string;
  insights?: InsightStat[];
  event_type?: string;
  player?: string;
  team?: string;
  minute?: number;
  score?: string;
};

function formatEventType(value?: string) {
  if (!value) return 'Event';
  return value.replaceAll('_', ' ');
}

function Badge({ label }: { label: string }) {
  return <span className="badge">{label}</span>;
}

export default function DashboardClient({ initialInsights }: { initialInsights: InsightItem[] }) {
  const [insights, setInsights] = useState<InsightItem[]>(initialInsights);
  const [isRefreshing, startRefresh] = useTransition();
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);

  const totalCards = insights.length;
  const leadCount = useMemo(() => insights.filter((item) => item.lead_story).length, [insights]);

  // Group insights by fixture_id
  const insightsByFixture = useMemo(() => {
    const groups: Record<string, InsightItem[]> = {};
    insights.forEach((item) => {
      if (!groups[item.fixture_id]) groups[item.fixture_id] = [];
      groups[item.fixture_id].push(item);
    });
    // Sort each group's items by minute or created_at descending (newest on top)
    // We assume they arrive sorted or we could sort by minute here:
    Object.values(groups).forEach(list => list.sort((a, b) => (b.minute || 0) - (a.minute || 0)));
    return groups;
  }, [insights]);

  async function refreshInsights() {
    startRefresh(async () => {
      const response = await fetch('/api/insights', { cache: 'no-store' });
      const data = response.ok ? await response.json() : [];
      setInsights(Array.isArray(data) ? data : []);
      setLastUpdated(new Date().toLocaleTimeString());
    });
  }

  async function decide(fixtureId: string, insightId: string, action: 'approve' | 'reject') {
    const actionKey = `${fixtureId}:${insightId}`;
    setPendingActionId(actionKey);

    try {
      const response = await fetch(`/api/decide/${fixtureId}/${insightId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action }),
      });

      if (!response.ok) {
        throw new Error('Action failed');
      }

      setInsights((current) => current.filter((item) => item.id !== insightId));
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <div className="hero__eyebrow">Sky Sports</div>
        <div className="hero__row">
          <div>
            <h1>Soccer Saturday Live Insights</h1>
            <p>
              Production-ready review dashboard for editorial insight approval, backed by the Python
              ingestion pipeline.
            </p>
          </div>
          <div className="hero__stats">
            <Badge label="LIVE" />
            <Badge label={`${totalCards} pending`} />
            <Badge label={`${leadCount} with lead stories`} />
          </div>
        </div>
        <div className="hero__meta">
          <span>{new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
          <span>{lastUpdated ? `Updated ${lastUpdated}` : 'Auto-refresh ready'}</span>
          <button className="button button--ghost" onClick={refreshInsights} disabled={isRefreshing}>
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </header>

      <section className="content">
        {insights.length === 0 ? (
          <div className="empty-state">
            <h2>No pending insights</h2>
            <p>Run the match simulator or wait for the Pub/Sub feed to populate the dashboard.</p>
          </div>
        ) : (
          Object.entries(insightsByFixture).map(([fixtureId, items]) => (
            <div key={fixtureId} className="match-group">
              <h2>{fixtureId.replaceAll('-', ' ')}</h2>
              <div className="timeline">
                {items.map((item) => {
                  const actionKeyApprove = `${fixtureId}:${item.id}:approve`;
                  const actionKeyReject = `${fixtureId}:${item.id}:reject`;
                  return (
                    <article className="timeline-event" key={item.id}>
                      <div className="card__topline">
                        <Badge label={formatEventType(item.event_type)} />
                        <Badge label={`${item.minute ?? '—'}'`} />
                        <Badge label={item.score ?? 'n/a'} />
                      </div>
                      <h3>{item.lead_story ?? 'Untitled insight'}</h3>
                      <div className="card__subline">
                        {item.player ? <span>{item.player}</span> : <span>Unknown player</span>}
                        <span> • {item.team ?? 'Unknown team'}</span>
                      </div>
                      <ul className="insights-list">
                        {(item.insights ?? []).map((insight) => (
                          <li key={`${item.id}-${insight.category}`}>
                            <strong>{insight.category.replaceAll('_', ' ')}</strong>
                            <span>{insight.line}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="card__actions">
                        <button
                          className="button button--approve"
                          onClick={() => decide(fixtureId, item.id, 'approve')}
                          disabled={pendingActionId === actionKeyApprove || pendingActionId === actionKeyReject}
                        >
                          Approve
                        </button>
                        <button
                          className="button button--reject"
                          onClick={() => decide(fixtureId, item.id, 'reject')}
                          disabled={pendingActionId === actionKeyApprove || pendingActionId === actionKeyReject}
                        >
                          Reject
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </section>
    </main>
  );
}
