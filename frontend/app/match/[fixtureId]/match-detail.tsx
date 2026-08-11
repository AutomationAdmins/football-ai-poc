'use client';

import { useState, useTransition, useEffect } from 'react';

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

const logoMap: Record<string, string> = {
  'arsenal': 'arsenal.png',
  'chelsea': 'Chelsea.png',
  'leeds': 'leeds united.png',
  'sunderland': 'Sunderland.png',
  'manchester city': 'manchester city.svg',
  'man city': 'manchester city.svg',
  'manchester united': 'manchester united.png',
  'man utd': 'manchester united.png',
  'crystal palace': 'crystal palace.png',
  'tottenham': 'tottenham.png',
  'middlesbrough': 'Middlesbrough.png',
  'newcastle': 'Newcastle United.png',
  'sheffield': 'Sheffield United.png'
};

function getTeamLogo(teamName: string) {
  const normalized = teamName.toLowerCase().trim();
  if (logoMap[normalized]) {
    return `/logos/${logoMap[normalized]}`;
  }
  const stripped = normalized.replace(/ united| fc| city| utd/g, '').trim();
  for (const [key, filename] of Object.entries(logoMap)) {
    if (stripped.length > 2 && (key.includes(stripped) || stripped.includes(key))) {
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
  return { home: home.replace(/-/g, ' '), away: away.replace(/-/g, ' ') };
}

function formatEventType(value?: string) {
  if (!value) return 'Event';
  return value.replaceAll('_', ' ');
}

function Badge({ label, type = 'light' }: { label: string; type?: 'light' | 'dark' | 'red' | 'green' | 'yellow' }) {
  return <span className={`badge badge--${type}`}>{label}</span>;
}

export default function MatchDetail({ fixtureId, initialInsights }: { fixtureId: string; initialInsights: InsightItem[] }) {
  const [insights, setInsights] = useState<InsightItem[]>(initialInsights);
  const [isRefreshing, startRefresh] = useTransition();

  const items = [...insights].sort((a, b) => (b.minute || 0) - (a.minute || 0));
  const { home, away } = parseFixtureId(fixtureId);
  const homeLogo = getTeamLogo(home);
  const awayLogo = getTeamLogo(away);
  const latestScore = items[0]?.score ?? '0-0';
  const latestMinute = items[0]?.minute ?? 0;

  async function refreshInsights() {
    startRefresh(async () => {
      const response = await fetch('/api/insights', { cache: 'no-store' });
      const data = response.ok ? await response.json() : [];
      const filtered = (Array.isArray(data) ? data : []).filter((i: InsightItem) => i.fixture_id === fixtureId);
      setInsights(filtered);
    });
  }

  useEffect(() => {
    const interval = setInterval(() => refreshInsights(), 500);
    return () => clearInterval(interval);
  }, []);

  return (
    <main className="shell">
      {/* Back button */}
      <a href="/" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#58a6ff', textDecoration: 'none', fontSize: '0.9rem', marginBottom: '16px', padding: '8px 0' }}>
        ← Back to all matches
      </a>

      {/* Scoreboard */}
      <div className="scoreboard" style={{ marginBottom: '24px' }}>
        <div className="scoreboard__header">
          <span>{fixtureId.includes('leeds') || fixtureId.includes('sunderland') ? 'EFL Championship' : 'Premier League'}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div className={isRefreshing ? 'dot-blinking' : ''} style={{ width: '8px', height: '8px', backgroundColor: '#ef4444', borderRadius: '50%' }} />
            <span style={{ fontSize: '0.75rem', color: '#ef4444', fontWeight: 600 }}>LIVE</span>
          </div>
        </div>
        <div className="scoreboard__teams">
          <div className="scoreboard__team">
            {homeLogo ? <img src={homeLogo} alt={home} className="scoreboard__logo" /> : <div className="scoreboard__logo" />}
            <span className="scoreboard__team-name">{home}</span>
          </div>
          <div className="scoreboard__score-area">
            <div className="scoreboard__score">{latestScore}</div>
            <div className="scoreboard__minute">{latestMinute >= 90 ? 'FT' : `${latestMinute}'`}</div>
          </div>
          <div className="scoreboard__team">
            {awayLogo ? <img src={awayLogo} alt={away} className="scoreboard__logo" /> : <div className="scoreboard__logo" />}
            <span className="scoreboard__team-name">{away}</span>
          </div>
        </div>
      </div>

      {/* Events Timeline */}
      <div style={{ fontSize: '0.8rem', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px' }}>
        Match Events ({items.length})
      </div>

      {items.length === 0 ? (
        <div className="empty-state">
          <h2>No events yet</h2>
          <p>Waiting for match data...</p>
        </div>
      ) : (
        <div className="timeline">
          {items.map((item, index) => {
            return (
              <article className="event-card" key={item.id}>
                <div className="event-card__header">
                  <div className="event-card__eyebrow" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    {index === 0 && <Badge label="LATEST" type="red" />}
                    <Badge label={formatEventType(item.event_type)} type="dark" />
                    <span style={{ color: '#8b949e', fontSize: '0.8rem' }}>{item.minute}&apos;</span>
                    {item.player && <span style={{ color: '#c9d1d9', fontSize: '0.85rem' }}>· {item.player}</span>}
                  </div>
                  <h3 className="event-card__title">
                    {item.lead_story ?? 'Untitled insight'}
                  </h3>
                </div>

                <div className="event-card__body">
                  <ul className="insights-list">
                    {(item.insights ?? []).map((insight, idx) => (
                      <li key={`${item.id}-${idx}`}>
                        <div className="insight-number">{idx + 1}</div>
                        <div className="insight-text">{insight.line}</div>
                        <Badge
                          label={insight.category.replaceAll('_', ' ')}
                          type={insight.category.includes('impact') ? 'yellow' : 'light'}
                        />
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </main>
  );
}
