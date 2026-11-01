const $ = (id) => document.getElementById(id);
function showPage(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === page));
  document.querySelectorAll('.nav').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  window.scrollTo({top: document.querySelector('.hero').offsetTop - 85, behavior:'smooth'});
}
document.querySelectorAll('.nav').forEach(b => b.addEventListener('click', () => showPage(b.dataset.page)));

// Welcome promo + optional original waiting music. Browsers require a user gesture before audio starts.
let musicOn = false, audioContext = null, musicTimer = null, noteIndex = 0, adTimer = null;
const melody = [261.63, 329.63, 392.00, 329.63, 293.66, 349.23, 440.00, 349.23];
function playNote() {
  if (!musicOn || !audioContext) return;
  const now = audioContext.currentTime;
  const osc = audioContext.createOscillator();
  const gain = audioContext.createGain();
  osc.type = 'sine'; osc.frequency.value = melody[noteIndex % melody.length];
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.035, now + 0.08);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.65);
  osc.connect(gain); gain.connect(audioContext.destination); osc.start(now); osc.stop(now + 0.7);
  noteIndex++;
}
async function toggleMusic(force) {
  musicOn = typeof force === 'boolean' ? force : !musicOn;
  const btn = $('musicToggle');
  btn.textContent = musicOn ? '♫ Waiting music: ON' : '♫ Turn waiting music on';
  btn.setAttribute('aria-pressed', String(musicOn));
  if (musicOn) {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) throw new Error('Audio is not supported by this browser.');
      audioContext ||= new AudioCtx();
      if (audioContext.state === 'suspended') await audioContext.resume();
      playNote(); clearInterval(musicTimer); musicTimer = setInterval(playNote, 720);
    } catch (e) { musicOn = false; btn.textContent = '♫ Music unavailable'; btn.setAttribute('aria-pressed','false'); }
  } else { clearInterval(musicTimer); musicTimer = null; }
}
$('musicToggle').addEventListener('click', () => toggleMusic());
$('enterBtn').addEventListener('click', () => {
  const countdown = $('adCountdown');
  const enter = $('enterBtn');
  enter.disabled = true; enter.textContent = 'Preparing your hangar…';
  countdown.textContent = 'Advertisement · 10 seconds remaining';
  let seconds = 10;
  clearInterval(adTimer);
  adTimer = setInterval(() => {
    seconds--;
    if (seconds > 0) countdown.textContent = `Advertisement · ${seconds} seconds remaining`;
    else {
      clearInterval(adTimer); countdown.textContent = 'Welcome aboard!';
      $('welcome').classList.add('hide');
      enter.disabled = false; enter.innerHTML = 'Enter Air Travel <span>→</span>';
      if (musicOn) toggleMusic(true);
    }
  }, 1000);
});

function safe(text) {
  return String(text || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function renderMessages(items) {
  $('messages').innerHTML = items.map(m => `<div class="message"><div class="avatar">${safe((m.name||'A').slice(0,1).toUpperCase())}</div><div class="bubble"><b>${safe(m.name)} <time>${safe(m.time)}</time></b>${safe(m.text)}${m.image ? `<img src="${safe(m.image)}" alt="Shared aviation picture">` : ''}</div></div>`).join('');
  $('messages').scrollTop = $('messages').scrollHeight;
}
async function loadMessages() {
  try { const r = await fetch('/api/messages'); renderMessages(await r.json()); }
  catch(e) { $('messages').textContent = 'Could not load messages.'; }
}
$('chatForm').addEventListener('submit', async e => {
  e.preventDefault();
  if (!window.AIRTRAVEL_SIGNED_IN) { alert('Please open Sign in / Join and create an account or sign in before posting.'); showPage('auth'); return; }
  const fd = new FormData();
  fd.append('name', $('nameInput').value || 'Guest');
  fd.append('text', $('messageInput').value);
  if ($('imageInput').files[0]) fd.append('image', $('imageInput').files[0]);
  try {
    const r = await fetch('/api/messages', {method:'POST', body:fd});
    const data = await r.json();
    if (!r.ok) { if (r.status === 401) showPage('auth'); return alert(data.error || 'Message could not be sent.'); }
    $('messageInput').value = ''; $('imageInput').value = ''; await loadMessages();
  } catch(err) { alert('The local server is not responding.'); }
});
loadMessages();
setInterval(loadMessages, 5000);

let flightMap = null;
let flightMarkers = [];
function initFlightMap() {
  if (!window.L || !$('flightMap') || flightMap) return;
  flightMap = L.map('flightMap').setView([6.5244, 3.3792], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
  }).addTo(flightMap);
  L.circleMarker([6.5244, 3.3792], {radius:5}).addTo(flightMap).bindPopup('Lagos, Nigeria');
}
async function loadFlights() {
  try {
    const data = await (await fetch('/api/flights')).json();
    initFlightMap();
    $('flightCount').textContent = `${String(data.flights.length).padStart(2,'0')} aircraft`;
    const status = $('flightStatus');
    if (status) {
      status.textContent = data.demo ? 'SAMPLE DATA — LIVE FEED UNAVAILABLE' : `LIVE ADS-B · ${data.updated || 'updated'}`;
      status.classList.toggle('warning', !!data.demo);
      status.title = data.notice || 'Public ADS-B reports are not guaranteed to be complete or current.';
    }
    $('flightList').innerHTML = data.flights.map(f => `<div class="flight-row"><div><b>${safe(f.callsign)}</b><small>${safe(f.from)} · ${safe(f.hex || '')}</small></div><div class="flight-meta"><strong>${safe(f.status)}</strong>${safe(f.altitude)} · ${safe(f.speed)}</div></div>`).join('') || '<p class="data-note">No aircraft reports in this area right now. Try refreshing later.</p>';
    flightMarkers.forEach(m => m.remove()); flightMarkers = [];
    if (flightMap) data.flights.forEach(f => {
      if (Number.isFinite(Number(f.lat)) && Number.isFinite(Number(f.lon))) {
        const marker = L.marker([Number(f.lat), Number(f.lon)]).addTo(flightMap);
        marker.bindPopup(`<b>${safe(f.callsign)}</b><br>${safe(f.altitude)} · ${safe(f.speed)}<br>${safe(f.status)}`);
        flightMarkers.push(marker);
      }
    });
  } catch(e) { $('flightList').textContent = 'Could not load flight data. Check your internet connection.'; }
}
loadFlights();
setInterval(loadFlights, 60000);

async function askAI(prompt) {
  $('aiAnswer').textContent = 'Air Travel AI is thinking…';
  try {
    const r = await fetch('/api/ai', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt})});
    const data = await r.json(); $('aiAnswer').textContent = data.answer; if ($('aiMode') && data.mode) $('aiMode').textContent = data.mode;
  } catch(e) { $('aiAnswer').textContent = 'AI demo is unavailable while the server is offline.'; }
}
$('aiForm').addEventListener('submit', e => {e.preventDefault(); const q=$('aiPrompt').value.trim(); if(q){askAI(q);$('aiPrompt').value='';}});
document.querySelectorAll('.suggestions button').forEach(b => b.addEventListener('click', () => askAI(b.textContent)));
if (document.querySelector('#stats')) {
  fetch('/api/owner/stats').then(r=>r.json()).then(s=>{
    if(s.error) return;
    $('stats').innerHTML = `<div><small>Messages</small><b>${s.messages}</b></div><div><small>Image uploads</small><b>${s.uploads}</b></div><div><small>Demo flights</small><b>${s.flights}</b></div>`;
  });
}
if (new URLSearchParams(location.search).has('owner_error')) alert('That owner password was not correct.');

const authParams = new URLSearchParams(location.search);
const authNotice = $('authNotice');
if (authNotice) {
  const err = authParams.get('auth_error');
  if (err === 'invalid_signup') authNotice.textContent = 'Please use a username of at least 3 characters, a valid email and a password of at least 8 characters.';
  else if (err === 'exists') authNotice.textContent = 'That username or email is already registered. Please sign in instead.';
  else if (err === 'login') authNotice.textContent = 'Sign in failed. Check your username/email and password.';
  else if (authParams.get('auth_success') === 'joined') authNotice.textContent = 'Account created successfully. Welcome aboard!';
  else if (authParams.get('auth_success') === 'welcome') authNotice.textContent = 'You are signed in. Welcome back!';
  else if (authParams.get('auth_success') === 'logout') authNotice.textContent = 'You have signed out.';
}
