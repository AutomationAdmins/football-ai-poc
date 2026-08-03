// Football AI Dashboard - JavaScript
// Preserve all existing functionality

// Set current date in header
(function() {
    const now = new Date();
    const options = { day: 'numeric', month: 'short', year: 'numeric' };
    const formatted = now.toLocaleDateString('en-GB', options);
    document.getElementById('current-date').textContent = '📅 ' + formatted;
})();

const leaguePresets = {
    'Premier League': {
        team: 'Arsenal',
        opponent: 'Chelsea',
        player: 'Bukayo Saka',
        score: '2-1',
    },
    'EFL Championship': {
        team: 'Leeds United',
        opponent: 'Sunderland',
        player: 'Crysencio Summerville',
        score: '1-1',
    },
};

function applyLeaguePreset(inputIndex) {
    const league = document.getElementById(`input-${inputIndex}-league`).value;
    const preset = leaguePresets[league];

    if (!preset) {
        return;
    }

    document.getElementById(`input-${inputIndex}-team`).value = preset.team;
    document.getElementById(`input-${inputIndex}-opponent`).value = preset.opponent;
    document.getElementById(`input-${inputIndex}-player`).value = preset.player;
    document.getElementById(`input-${inputIndex}-score`).value = preset.score;
}

function buildInputPayload(inputIndex) {
    return {
        event: document.getElementById(`input-${inputIndex}-event`).value,
        league: document.getElementById(`input-${inputIndex}-league`).value || null,
        player: document.getElementById(`input-${inputIndex}-player`).value || null,
        team: document.getElementById(`input-${inputIndex}-team`).value || null,
        opponent: document.getElementById(`input-${inputIndex}-opponent`).value || null,
        minutes: parseInt(document.getElementById(`input-${inputIndex}-minutes`).value) || null,
        score: document.getElementById(`input-${inputIndex}-score`).value || null,
    };
}

async function sendEvent() {
    const payload = {
        input_1: buildInputPayload(1),
        input_2: buildInputPayload(2),
    };

    const msg = document.getElementById('status-msg');
    msg.style.color = '#58a6ff';
    msg.textContent = 'Sending both events...';

    try {
        const res = await fetch('/event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.status === 'error') {
            msg.textContent = `AI error: ${data.reason}`;
            msg.style.color = '#da3633';
        } else {
            msg.textContent = 'Both inputs processed — refreshing dashboard...';
            setTimeout(() => location.href = '/?show_results=1', 600);
        }
    } catch (e) {
        msg.style.color = '#da3633';
        msg.textContent = `Error: ${e.message}`;
    }
}

async function decide(eventIndex, insightIndex, action) {
    const endpoint = action === 'approve'
        ? `/approve/${eventIndex}/${insightIndex}`
        : `/reject/${eventIndex}/${insightIndex}`;
    await fetch(endpoint, { method: 'POST' });

    const item = document.getElementById(`insight-${eventIndex}-${insightIndex}`);
    item.classList.add(action === 'approve' ? 'approved' : 'rejected');

    const actionsDiv = document.getElementById(`acts-${eventIndex}-${insightIndex}`);
    const badge = document.createElement('span');
    badge.className = `decision-done ${action === 'approve' ? 'dec-approved' : 'dec-rejected'}`;
    badge.textContent = action === 'approve' ? 'APPROVED' : 'REJECTED';
    actionsDiv.innerHTML = '';
    actionsDiv.appendChild(badge);
}

// Initialize presets on page load
applyLeaguePreset(1);
document.getElementById('input-2-league').value = 'EFL Championship';
applyLeaguePreset(2);
