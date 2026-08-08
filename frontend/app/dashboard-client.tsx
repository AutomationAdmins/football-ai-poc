'use client';

import { useMemo, useState, useTransition, useEffect } from 'react';
import Image from 'next/image';

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

// Map team names to exact logo filenames in /public/logos/
const logoMap: Record<string, string> = {
  'arsenal': 'arsenal.png',
  'chelsea': 'Chelsea.png',
  'leeds': 'leeds united.png',
  'sunderland': 'Sunderland.png',
  'manchester city': 'manchester city.png',
  'middlesbrough': 'Middlesbrough.png',
  'newcastle': 'Newcastle United.png',
  'sheffield': 'Sheffield United.png'
};

function getTeamLogo(teamName: string) {
  const normalized = teamName.toLowerCase().replace(/ united| fc| city/g, '').trim();
  for (const [key, filename] of Object.entries(logoMap)) {
    if (normalized.includes(key) || key.includes(normalized)) {
      return `/logos/${filename}`;
    }
  }
  return null;
}

function parseFixtureId(fixtureId: string) {
  // e.g. "arsenal-vs-chelsea-2025-08-02" -> ["Arsenal", "Chelsea"]
  const parts = fixtureId.split('-vs-');
  if (parts.length !== 2) return { home: 'Home', away: 'Away' };
  
  const home = parts[0];
  const awayParts = parts[1].split('-');
  
  // Try to extract just the team name before the date
  let away = awayParts[0];
  if (awayParts.length > 3) {
    // If there's a year-month-day, it's usually the last 3 parts
    away = awayParts.slice(0, awayParts.length - 3).join(' ');
  }

  return {
    home: home.replace(/-/g, ' '),
    away: away.replace(/-/g, ' ')
  };
}

function formatEventType(value?: string) {
  if (!value) return 'Event';
  return value.replaceAll('_', ' ');
}

function Badge({ label, type = 'light' }: { label: string, type?: 'light' | 'dark' | 'red' | 'green' | 'yellow' }) {
  return <span className={`badge badge--${type}`}>{label}</span>;
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

  useEffect(() => {
    const interval = setInterval(() => {
      refreshInsights();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  async function decide(fixtureId: string, insightId: string, action: 'approve' | 'reject') {
    const actionKey = `${fixtureId}:${insightId}`;
    setPendingActionId(actionKey);

    try {
      const response = await fetch(`/api/decide/${fixtureId}/${insightId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });

      if (!response.ok) throw new Error('Action failed');
      setInsights((current) => current.filter((item) => item.id !== insightId));
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <main className="shell">
      <header className="hero">
        <div className="hero__eyebrow" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', marginLeft: '0', background: 'white', padding: '4px 8px', borderRadius: '6px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
            <img src="/logos/skysports.png" alt="Sky Sports" style={{ height: '24px', objectFit: 'contain' }} />
          </div>
          <div style={{ display: 'flex', gap: '16px', fontSize: '0.85rem', color: '#bfdbfe', fontWeight: 500 }}>
            <span>{new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
            <span>{lastUpdated ? `Updated ${lastUpdated}` : 'Auto-refresh ready'}</span>
          </div>
        </div>
        <div className="hero__row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ margin: 0 }}>Soccer Saturday - Intelligent Insights Generator</h1>
          </div>
          <div className="hero__stats" style={{ display: 'flex', alignItems: 'center' }}>
            <div 
              onClick={refreshInsights}
              title="Click to refresh data"
              style={{ 
                cursor: 'pointer', 
                display: 'flex', 
                alignItems: 'center', 
                gap: '8px',
                padding: '4px 12px',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '999px',
                transition: 'opacity 0.2s'
              }}
            >
              <div 
                className={isRefreshing ? 'dot-blinking' : ''}
                style={{ 
                  width: '10px', 
                  height: '10px', 
                  backgroundColor: '#ef4444', 
                  borderRadius: '50%',
                  boxShadow: '0 0 8px #ef4444'
                }} 
              />
              <span style={{ color: 'white', fontWeight: 700, fontSize: '0.9rem', letterSpacing: '0.5px' }}>
                LIVE
              </span>
            </div>
          </div>
        </div>
      </header>

      <section className="content">
        {insights.length === 0 ? (
          <div className="empty-state">
            <h2>No pending insights</h2>
            <p>Run the match simulator or wait for the Pub/Sub feed to populate the dashboard.</p>
          </div>
        ) : (
          Object.entries(insightsByFixture).map(([fixtureId, items]) => {
            const { home, away } = parseFixtureId(fixtureId);
            const homeLogo = getTeamLogo(home);
            const awayLogo = getTeamLogo(away);
            
            // Latest score and minute from the most recent event (index 0 because we sorted desc)
            const latestScore = items[0]?.score ?? '0-0';
            const latestMinute = items[0]?.minute ?? 0;

            return (
              <div key={fixtureId} className="match-group">
                {/* Scoreboard Header */}
                <div className="scoreboard">
                  <div className="scoreboard__header">
                    <span>Premier League</span>
                    <span>{fixtureId}</span>
                  </div>
                  <div className="scoreboard__teams">
                    <div className="scoreboard__team">
                      {homeLogo ? <img src={homeLogo} alt={home} className="scoreboard__logo" /> : <div className="scoreboard__logo" />}
                      <span className="scoreboard__team-name">{home}</span>
                    </div>
                    
                    <div className="scoreboard__score-area">
                      <div className="scoreboard__score">{latestScore}</div>
                      <div className="scoreboard__minute">{latestMinute}'</div>
                      {items[0] && (
                        <div className="scoreboard__recent-event">
                          <Badge label={formatEventType(items[0].event_type)} type="red" />
                          {items[0].player && <span className="scoreboard__recent-player">{items[0].player}</span>}
                        </div>
                      )}
                    </div>
                    
                    <div className="scoreboard__team">
                      {awayLogo ? <img src={awayLogo} alt={away} className="scoreboard__logo" /> : <div className="scoreboard__logo" />}
                      <span className="scoreboard__team-name">{away}</span>
                    </div>
                  </div>
                </div>

                {/* Timeline Events */}
                <div className="timeline">
                  {items.map((item, index) => {
                    const actionKeyApprove = `${fixtureId}:${item.id}:approve`;
                    const actionKeyReject = `${fixtureId}:${item.id}:reject`;
                    const isProcessing = pendingActionId === actionKeyApprove || pendingActionId === actionKeyReject;

                    return (
                      <article className="event-card" key={item.id}>
                        <div className="event-card__header">
                          <div className="event-card__eyebrow" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                            {index === 0 && <Badge label="NEW" type="red" />}
                            Event {items.length - index} — {formatEventType(item.event_type)}
                          </div>
                          <h3 className="event-card__title">
                            {item.lead_story ?? 'Untitled insight'}
                          </h3>
                        </div>
                        
                        <div className="event-card__body">
                          <ul className="insights-list">
                            {(item.insights ?? []).map((insight, idx) => (
                              <li key={`${item.id}-${insight.category}`}>
                                <div className="insight-number">{idx + 1}</div>
                                <div className="insight-text">{insight.line}</div>
                                <Badge 
                                  label={insight.category.replaceAll('_', ' ')} 
                                  type={insight.category.includes('IMPACT') ? 'yellow' : 'light'} 
                                />
                              </li>
                            ))}
                          </ul>
                        </div>
                        
                        <div className="event-card__actions">
                          <button
                            className="button button--approve"
                            onClick={() => decide(fixtureId, item.id, 'approve')}
                            disabled={isProcessing}
                          >
                            ✓ Approve
                          </button>
                          <button
                            className="button button--reject"
                            onClick={() => decide(fixtureId, item.id, 'reject')}
                            disabled={isProcessing}
                          >
                            × Reject
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </section>
    </main>
  );
}
