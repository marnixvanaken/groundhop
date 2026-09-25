/* GroundHop — gedeelde helpers voor alle schermen.

   Beeld doet hier werk, het is geen versiering: een clublogo vervangt een
   clubnaam, een portret maakt een opstelling leesbaar als mensen, een vlag
   draagt de nationaliteit die anders een landcode zou zijn.

   Van de 3016 spelers staan er 300 lokaal, dus elke afbeelding heeft een
   terugval nodig die er niet uitziet als een fout.
*/

const DAG = ['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag'];
const MND = ['januari','februari','maart','april','mei','juni','juli','augustus',
             'september','oktober','november','december'];
const KORT = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];

function datum(iso, voluit){
  const d = new Date(iso + 'T12:00:00');
  return voluit
    ? `${DAG[d.getDay()]} ${d.getDate()} ${MND[d.getMonth()]} ${d.getFullYear()}`
    : `${d.getDate()} ${KORT[d.getMonth()]} ${d.getFullYear()}`;
}

const getal = n => n == null ? '—' : n.toLocaleString('nl-NL');
const comp  = n => n.replace('VriendenLoterij ', '').replace('Eurojackpot ', '');

/* Vlaggen als emoji in plaats van plaatjes: geen bestanden, geen netwerk, en
   op iOS tekent het systeem ze zelf. De bron gebruikt eigen codes voor de
   Britse landsdelen, die als tag-reeks hun eigen vlag hebben. Noord-Ierland
   heeft er geen; daar blijft de landcode staan. */
const LANDSDEEL = {en:'gbeng', sx:'gbsct', wl:'gbwls', wa:'gbwls'};

function vlag(a2){
  if (!a2) return '';
  const code = a2.toLowerCase();
  const deel = LANDSDEEL[code];
  if (deel){
    return '\u{1F3F4}' + [...deel].map(c => String.fromCodePoint(0xE0000 + c.charCodeAt(0))).join('')
           + '\u{E007F}';
  }
  if (code.length !== 2) return '';
  return [...code].map(c => String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 97)).join('');
}

function initialen(naam, letters){
  return naam.replace(/^(FC|AFC|SC|Jong|RSC|KAA)\s+/, '')
             .split(/[\s.]+/).map(w => w[0] || '').join('')
             .slice(0, letters).toUpperCase();
}

/* Eén renderer voor alle afbeeldingen. Ontbreekt het bestand of laadt het
   niet, dan komt er een cirkel met initialen in plaats van een kapot icoon. */
function beeld(src, klasse, fallbackKlasse, tekst){
  const terugval = `<div class="${fallbackKlasse}">${tekst}</div>`;
  if (!src) return terugval;
  const escaped = terugval.replace(/"/g, '&quot;');
  return `<img class="${klasse}" src="${src}" alt="" loading="lazy" onerror="this.outerHTML='${escaped}'">`;
}

const logo    = (src, naam, mini) =>
  beeld(src, mini ? 'crest-mini' : 'crest',
        mini ? 'crest-fallback mini' : 'crest-fallback', initialen(naam, 3));

const portret = (src, naam) =>
  beeld(src, 'avatar', 'avatar-fallback', initialen(naam, 2));

const compLogo = src => src
  ? `<img class="comp-logo" src="${src}" alt="" loading="lazy" onerror="this.remove()">`
  : '';

/* Eén duel als rij in een lijst, voor elk scherm hetzelfde. Alleen het
   element en wat er rechts staat mogen verschillen: een link met een pijl,
   of een knop met een keuzebolletje.

   Een wedstrijd die nog gespeeld moet worden heeft geen uitslag; dan blijft
   die kolom leeg in plaats van een verzonnen 0–0 te tonen. */
function duel(m, {tag = 'a', attrs = '', eind = '<span class="chev" aria-hidden="true">›</span>'} = {}){
  const uitslag = m.home_score != null && m.away_score != null
    ? `${m.home_score}–${m.away_score}` : (m.score || '');
  return `
    <${tag} class="duel"${attrs}>
      <span class="duel-crests">${logo(m.home_crest, m.home, true)}${logo(m.away_crest, m.away, true)}</span>
      <span class="duel-main">
        <span class="duel-teams">${m.home} – ${m.away}</span>
        <span class="duel-meta">${datum(m.date)} · ${comp(m.tournament)}</span>
      </span>
      <span class="duel-score num">${uitslag}</span>
      ${eind}
    </${tag}>`;
}

const seizoenLabel = j => `${String(j).slice(2)}/${String(j + 1).slice(2)}`;
const esc = t => String(t ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

/* ── Data ────────────────────────────────────────────────────────────────
   Alles komt uit window.APP (app-data.js) en window.SPELERS (speler-data.js),
   gebouwd door demo/build_app_data.py. Opzoeken gebeurt lui, zodat de
   volgorde van de scripttags er niet toe doet. */
let _clubs, _wedstrijden;
function club(id){
  if (!_clubs){ _clubs = {}; (window.APP?.clubs || []).forEach(c => _clubs[c.id] = c); }
  return _clubs[id] || {id, name: '?', crest: null, count: 0};
}
function wedstrijd(id){
  if (!_wedstrijden){ _wedstrijden = {}; (window.APP?.matches || []).forEach(m => _wedstrijden[m.id] = m); }
  return _wedstrijden[id];
}
const stadion = key => (window.APP?.venues || []).find(v => v.key === key);

const wedstrijdHref = id  => `wedstrijddetail.html#id=${id}`;
const stadionHref   = key => `stadiondetail.html#v=${encodeURIComponent(key)}`;
const spelerHref    = id  => `speler.html#id=${id}`;
const clubHref      = id  => `club.html#id=${id}`;
const compHref      = naam => `competitie.html#t=${encodeURIComponent(naam)}`;

/* Een wedstrijd uit APP in de vorm die duel() leest. */
function alsDuel(m){
  const h = club(m.hid), a = club(m.aid);
  return {date: m.date, tournament: m.t, home: h.name, away: a.name,
          home_crest: h.crest, away_crest: a.crest, home_score: m.hs, away_score: m.as};
}
const duelLink = m => duel(alsDuel(m), {attrs: ` href="${wedstrijdHref(m.id)}"`});

/* Parameters staan achter de # en niet achter de ?: een statische host kan
   een querystring weggooien, een hash nooit. */
const param = naam => new URLSearchParams(location.hash.slice(1)).get(naam);

/* ── Navigatie ─────────────────────────────────────────────────────────── */
const TABS = [
  ['home',    'index.html',   'Home',    '<path d="M3 10.5 12 3l9 7.5V21H3z"/>'],
  ['duels',   'duels.html',   'Duels',   '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/>'],
  ['grounds', 'grounds.html', 'Grounds', '<path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>'],
  ['spelers', 'spelers.html', 'Spelers', '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6"/>'],
  ['meer',    'meer.html',    'Meer',    '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>'],
];

/* Een detailscherm dat onder meer dan één tab hangt (een club zie je vanaf
   Home, Meer en elke wedstrijd) houdt de tab actief waar je vandaan kwam,
   zoals op iOS. Zonder geheugen valt het terug op de tab die je meegeeft. */
function tabbalk(actief, vanHerkomst){
  try {
    if (vanHerkomst) actief = sessionStorage.getItem('gh-tab') || actief;
    else sessionStorage.setItem('gh-tab', actief);
  } catch {}
  document.querySelector('.tabbar').innerHTML = TABS.map(([k, href, label, svg]) =>
    `<a href="${href}"${k === actief ? ' aria-current="page"' : ''}>
       <svg viewBox="0 0 24 24" aria-hidden="true">${svg}</svg>${label}</a>`).join('');
}

/* De terugknop noemt het scherm waar je vandaan kwam, zoals op iOS. Is dat
   niet te achterhalen — een gedeelde link, een nieuw tabblad — dan wijst hij
   naar de lijst waar dit scherm onder valt. */
const TITELS = {
  'index.html': 'Home', 'duels.html': 'Duels', 'grounds.html': 'Grounds',
  'spelers.html': 'Spelers', 'meer.html': 'Meer', 'wedstrijddetail.html': 'Wedstrijd',
  'stadiondetail.html': 'Stadion', 'speler.html': 'Speler', 'toevoegen.html': 'Toevoegen',
  'club.html': 'Club', 'competitie.html': 'Competitie',
};

function vorigeScherm(){
  try {
    const r = new URL(document.referrer);
    if (r.origin !== location.origin) return null;
    const bestand = r.pathname.split('/').pop() || 'index.html';
    return TITELS[bestand] ? bestand : null;
  } catch { return null; }
}

function terugknop(label, href){
  const vorige = vorigeScherm();
  return `
    <a class="back" href="${href}" data-terug="${vorige ? 1 : ''}">
      <svg width="11" height="18" viewBox="0 0 11 18" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M9.5 1.5 2 9l7.5 7.5"/></svg>
      <span>${vorige ? TITELS[vorige] : label}</span>
    </a>`;
}

document.addEventListener('click', e => {
  const a = e.target.closest('[data-terug="1"]');
  if (a && history.length > 1){ e.preventDefault(); history.back(); }
});

/* ── Seizoensreeks ─────────────────────────────────────────────────────────
   Eén reeks, één kleur, geen legenda. Lege seizoenen staan als nul in de
   reeks: overslaan maakt van een onderbreking een doorlopende lijn. Alleen
   de hoogste staaf krijgt een zichtbaar getal; elke staaf draagt zijn waarde
   in de aria-tekst. */
function seizoensreeks(datums){
  const telling = {};
  datums.forEach(d => { const j = seizoenVan(d); telling[j] = (telling[j] || 0) + 1; });
  const jaren = Object.keys(telling).map(Number);
  if (jaren.length < 2) return null;
  const rijen = [];
  for (let j = Math.min(...jaren); j <= Math.max(...jaren); j++){
    rijen.push({name: seizoenLabel(j), value: telling[j] || 0});
  }
  const max = Math.max(...rijen.map(r => r.value));
  const leeg = rijen.filter(r => !r.value).length;
  // Een label past onder een staaf tot een seizoen of negen. Daarboven krijgt
  // elke zoveelste er een, geteld vanaf het laatste seizoen zodat het meest
  // recente altijd benoemd is.
  const stap = Math.ceil(rijen.length / 8);
  const toonLabel = i => (rijen.length - 1 - i) % stap === 0;
  return {rijen, leeg, html: `
    <div class="chart">
      <div class="bars" role="img"
           aria-label="Duels per seizoen: ${rijen.map(b => `${b.name} ${b.value}`).join(', ')}">
        ${rijen.map(b => `
          <div title="${b.name}: ${b.value} duels">
            <div class="bar-top num">${b.value === max ? b.value : ''}</div>
            <div class="bar-fill${b.value ? '' : ' leeg'}"
                 style="height:${b.value ? Math.max(4, b.value / max * 100) : 2}%"></div>
          </div>`).join('')}
      </div>
      <div class="bar-axis">${rijen.map((b, i) => `<span>${toonLabel(i) ? b.name : ''}</span>`).join('')}</div>
    </div>`};
}

function seizoenVan(iso){
  const j = +iso.slice(0, 4), m = +iso.slice(5, 7);
  return m >= 7 ? j : j - 1;
}

/* Een lijst met een verhoudingsbalkje eronder. */
function ranglijst(rijen){
  if (!rijen.length) return '';
  const max = Math.max(...rijen.map(r => r.count));
  return `<div class="rank">${rijen.map(r => `
    <${r.href ? `a href="${r.href}"` : 'div'} class="rank-item">
      <div class="rank-row">
        ${r.beeld || ''}
        <span class="naam">${r.name}</span>
        <span class="aantal num">${r.count}×</span>
      </div>
      <div class="rank-bar"><i style="width:${r.count / max * 100}%"></i></div>
    </${r.href ? 'a' : 'div'}>`).join('')}</div>`;
}

function zonderData(bestand){
  return `<div class="card"><div class="note" style="border-top:0">Geen data gevonden.
    Draai <code>python3 demo/build_app_data.py</code> en open deze pagina via
    <code>python3 server.py</code> op localhost:4000/demo/${bestand}.</div></div>`;
}

/* Diakrieten weg en alleen letters en cijfers, zodat 'munchen' München vindt
   en 'goahead' Go Ahead Eagles. */
const plat = t => String(t || '').toLowerCase().normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]/g, '');

/* Het zoekveld in de bovenbalk: zoekt terwijl je typt, wist met ✕ of Esc. */
function koppelZoekveld(bijInvoer){
  const veld = document.getElementById('zoek'), wis = document.getElementById('wis');
  veld.addEventListener('input', () => { wis.hidden = !veld.value; bijInvoer(veld.value.trim()); });
  wis.addEventListener('click', () => {
    veld.value = ''; wis.hidden = true; veld.focus(); bijInvoer('');
  });
  veld.addEventListener('keydown', e => { if (e.key === 'Escape') wis.click(); });
}

const POSITIE = {G: 'Keeper', D: 'Verdediger', M: 'Middenvelder', F: 'Aanvaller'};

function leeftijd(dob, op){
  if (!dob) return null;
  const a = new Date(dob + 'T12:00:00'), b = op ? new Date(op + 'T12:00:00') : new Date();
  let j = b.getFullYear() - a.getFullYear();
  if (b.getMonth() < a.getMonth() || (b.getMonth() === a.getMonth() && b.getDate() < a.getDate())) j--;
  return j;
}

const clubOpNaam = naam => (window.APP?.clubs || []).find(c => c.name === naam);
