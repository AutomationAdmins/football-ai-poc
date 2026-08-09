'use client';

import { useMemo, useState, useTransition, useEffect } from 'react';

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
  const parts = fixtureId.split('-vs-');
  if (parts.length !== 2) return { home: 'Home', away: 'Away' };
  
  const home = parts[0];
  const awayParts = parts[1].split('-');
  let away = awayParts[0];
  if (awayParts.length > 3) {
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

/**
 * Pick the single most important lead story across all matches.
 * Priority: GOAL with hat-trick > GOAL with equaliser > RED_CARD > any GOAL > other
 */
function pickLeadStory(insights: InsightItem[]): InsightItem | null {
  if (insights.length === 0) return null;

  const scored = insights
    .filter(i => i.lead_story)
    .map(i => {
      let weight = 0;
      const lead = (i.lead_story ?? '').toLowerCase();
      const eventType = (i.event_type ?? '').toUpperCase();

      // Hat-trick is the biggest story
      if (lead.includes('hat-trick') || lead.includes('hat trick')) weight += 100;
      // Equaliser or comeback
      if (lead.includes('equalis') || lead.includes('pulls one back')) weight += 60;
      // Red card drama
      if (eventType === 'RED_CARD') weight += 50;
      // Any goal
      if (eventType === 'GOAL') weight += 30;
      // League impact language
      if (lead.includes('promotion') || lead.includes('title') || lead.includes('relegation') || lead.includes('champions league')) weight += 40;
      // More recent = slight preference
      weight += (i.minute ?? 0) * 0.1;

      return { item: i, weight };
    })
    .sort((a, b) => b.weight - a.weight);

  return scored[0]?.item ?? null;
}

export default function DashboardClient({ initialInsights }: { initialInsights: InsightItem[] }) {
  const [insights, setInsights] = useState<InsightItem[]>(initialInsights);
  const [isRefreshing, startRefresh] = useTransition();
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

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

  const leadStory = useMemo(() => pickLeadStory(insights), [insights]);

  async function refreshInsights() {
    startRefresh(async () => {
      const response = await fetch('/api/insights', { cache: 'no-store' });
      const data = response.ok ? await response.json() : [];
      setInsights(Array.isArray(data) ? data : []);
      setLastUpdated(new Date().toLocaleTimeString());
    });
  }

  useEffect(() => {
    const interval = setInterval(() => refreshInsights(), 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="shell">
      {/* Header */}
      <header className="hero">
        <div className="hero__eyebrow" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', background: 'white', padding: '4px 8px', borderRadius: '6px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
            <img src="/logos/skysports.png" alt="Sky Sports" style={{ height: '24px', objectFit: 'contain' }} />
          </div>
          <div style={{ display: 'flex', gap: '16px', fontSize: '0.85rem', color: '#bfdbfe', fontWeight: 500 }}>
            <span>{new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
            <span>{lastUpdated ? `Updated ${lastUpdated}` : ''}</span>
          </div>
        </div>
        <div className="hero__row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ margin: 0 }}>Soccer Saturday Intelligent Insight Generator</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 12px', background: 'rgba(255,255,255,0.1)', borderRadius: '999px', cursor: 'pointer' }} onClick={refreshInsights}>
            <div className={isRefreshing ? 'dot-blinking' : ''} style={{ width: '10px', height: '10px', backgroundColor: '#ef4444', borderRadius: '50%', boxShadow: '0 0 8px #ef4444' }} />
            <span style={{ color: 'white', fontWeight: 700, fontSize: '0.9rem', letterSpacing: '0.5px' }}>LIVE</span>
          </div>
        </div>
      </header>

      {/* Lead Story Banner */}
      {leadStory && (
        <section className="lead-story-banner" style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderLeft: '4px solid #ef4444', borderRadius: '12px', padding: '20px 24px', marginBottom: '24px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <span style={{ background: '#ef4444', color: 'white', fontSize: '0.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Lead Story</span>
            <span style={{ color: '#64748b', fontSize: '0.8rem', fontWeight: 500 }}>{leadStory.minute}&apos; — {formatEventType(leadStory.event_type)}</span>
          </div>
          <p style={{ color: '#0f172a', fontSize: '1.2rem', fontWeight: 700, margin: 0, lineHeight: 1.4 }}>
            {leadStory.lead_story}
          </p>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: '8px 0 0', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>
            {leadStory.fixture_id.replace(/-/g, ' ').replace(/\d{4} \d{2} \d{2}/, '').trim()}
          </p>
        </section>
      )}

      {/* Score Cards Grid */}
      <section>
        {insights.length === 0 ? (
          <div className="empty-state">
            <h2>No live matches</h2>
            <p>Waiting for events...</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '24px', width: '100%' }}>
            {Object.entries(insightsByFixture).map(([fixtureId, items]) => {
              const { home, away } = parseFixtureId(fixtureId);
              const homeLogo = getTeamLogo(home);
              const awayLogo = getTeamLogo(away);
              const latestScore = items[0]?.score ?? '0-0';
              const latestMinute = items[0]?.minute ?? 0;
              const latestEvent = items[0];

              // Determine league from first item or fixture
              const league = fixtureId.includes('leeds') || fixtureId.includes('sunderland') ? 'EFL Championship' : 'Premier League';

              return (
                <a
                  key={fixtureId}
                  href={`/match/${encodeURIComponent(fixtureId)}`}
                  style={{ textDecoration: 'none', color: 'inherit' }}
                >
                  <div className="score-card" style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', padding: '16px', cursor: 'pointer', transition: 'all 0.2s ease', boxShadow: '0 2px 4px rgba(0,0,0,0.04)' }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = '#3b82f6'; e.currentTarget.style.boxShadow = '0 10px 15px -3px rgba(59, 130, 246, 0.1), 0 4px 6px -2px rgba(59, 130, 246, 0.05)'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.04)'; e.currentTarget.style.transform = 'translateY(0)'; }}
                  >
                    {/* League label */}
                    <div style={{ fontSize: '0.75rem', color: '#64748b', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                      <span style={{ color: '#3b82f6' }}>{league}</span>
                      <span style={{ color: latestMinute >= 90 ? '#64748b' : '#ef4444', background: latestMinute >= 90 ? 'transparent' : '#fee2e2', padding: latestMinute >= 90 ? '0' : '2px 8px', borderRadius: '4px' }}>
                        {latestMinute >= 90 ? 'FT' : `${latestMinute}'`}
                      </span>
                    </div>

                    {/* Teams and Score */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      {/* Home Team */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
                        {homeLogo ? <img src={homeLogo} alt={home} style={{ width: '36px', height: '36px', objectFit: 'contain' }} /> : <div style={{ width: '36px', height: '36px', background: '#f1f5f9', borderRadius: '50%' }} />}
                        <span style={{ color: '#0f172a', fontWeight: 700, fontSize: '1rem', textTransform: 'capitalize' }}>{home}</span>
                      </div>

                      {/* Score */}
                      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '8px 16px', borderRadius: '8px', minWidth: '76px', textAlign: 'center', boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.02)' }}>
                        <span style={{ color: '#0f172a', fontSize: '1.5rem', fontWeight: 800, letterSpacing: '1px' }}>{latestScore}</span>
                      </div>

                      {/* Away Team */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, justifyContent: 'flex-end' }}>
                        <span style={{ color: '#0f172a', fontWeight: 700, fontSize: '1rem', textTransform: 'capitalize' }}>{away}</span>
                        {awayLogo ? <img src={awayLogo} alt={away} style={{ width: '36px', height: '36px', objectFit: 'contain' }} /> : <div style={{ width: '36px', height: '36px', background: '#f1f5f9', borderRadius: '50%' }} />}
                      </div>
                    </div>

                    {/* Latest Event Preview */}
                    {latestEvent && (
                      <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #f1f5f9' }}>
                        <p style={{ color: '#475569', fontSize: '0.85rem', margin: 0, lineHeight: 1.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {latestEvent.lead_story}
                        </p>
                      </div>
                    )}

                    {/* Event count */}
                    <div style={{ marginTop: '12px', fontSize: '0.75rem', color: '#94a3b8', fontWeight: 500, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>{items.length} event{items.length !== 1 ? 's' : ''}</span>
                      <span style={{ color: '#3b82f6' }}>Click for details &rarr;</span>
                    </div>
                  </div>
                </a>
              );
            })}
          </div>
        )}
      </section>

      {/* Footer */}
      <footer style={{ marginTop: '48px', padding: '24px 0', borderTop: '1px solid #e2e8f0', textAlign: 'center', color: '#64748b', fontSize: '0.85rem' }}>
        <p>&copy; {new Date().getFullYear()} Sky Sports Football Editorial Dashboard. Powered by AI.</p>
      </footer>
    </main>
  );
}
