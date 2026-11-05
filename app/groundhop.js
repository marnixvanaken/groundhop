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

function vlagEmoji(code){
  const deel = LANDSDEEL[code];
  if (deel){
    return '\u{1F3F4}' + [...deel].map(c => String.fromCodePoint(0xE0000 + c.charCodeAt(0))).join('')
           + '\u{E007F}';
  }
  // Noord-Ierland heeft geen eigen vlag-emoji; letters zouden als fout lezen.
  if (code.length !== 2 || code === 'nx') return '';
  return [...code].map(c => String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 97)).join('');
}

/* Vlaggen als afbeelding, uit app/vlaggen/ (flag-icons, MIT). Een emoji
   tekent elk systeem anders, en Windows toont er alleen letters. Laadt de
   afbeelding niet, dan valt hij terug op de emoji. */
const VLAGBESTAND = {en: 'gb-eng', sx: 'gb-sct', wa: 'gb-wls', wl: 'gb-wls', nx: 'gb-nir'};
function vlag(a2, klasse = 'vlag-img'){
  if (!a2) return '';
  const code = a2.toLowerCase();
  return `<img class="${klasse}" src="vlaggen/${VLAGBESTAND[code] || code}.svg" alt="${esc(landNaam(code))}"`
       + ` loading="lazy" onerror="this.outerHTML='${vlagEmoji(code)}'">`;
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
   gebouwd door app/build_app_data.py. Opzoeken gebeurt lui, zodat de
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
// Het clublogo op Transfermarkt, voor een club die je nog nooit zag.
const tmWapen       = id  => `https://img.a.transfermarkt.technology/wappen/normquad/${id}.png`;
const albumHref     = id  => `album.html#id=${encodeURIComponent(id)}`;

/* Een wedstrijd uit APP in de vorm die duel() leest. */
function alsDuel(m){
  const h = club(m.hid), a = club(m.aid);
  return {date: m.date, tournament: m.t, home: h.name, away: a.name,
          home_crest: h.crest, away_crest: a.crest, home_score: m.hs, away_score: m.as};
}
const duelLink = m => duel(alsDuel(m), {attrs: ` href="${wedstrijdHref(m.id)}"`});

/* Een chiprij die niet op één regel past, schuift. Na opnieuw tekenen staat
   hij weer waar hij stond (vorige), met de gekozen chip in beeld; een
   vervaagde rand wijst aan aan welke kant er nog meer staat. */
function schuifrij(rij, vorige = 0){
  if (!rij) return;
  rij.scrollLeft = vorige;
  const knop = rij.querySelector('[aria-pressed="true"]');
  if (knop){
    const l = knop.offsetLeft, r = l + knop.offsetWidth, marge = 40;
    if (l - marge < rij.scrollLeft) rij.scrollLeft = l - marge;
    else if (r + marge > rij.scrollLeft + rij.clientWidth) rij.scrollLeft = r + marge - rij.clientWidth;
  }
  const rand = () => {
    rij.classList.toggle('meer-links', rij.scrollLeft > 1);
    rij.classList.toggle('meer-rechts', rij.scrollLeft + rij.clientWidth < rij.scrollWidth - 1);
  };
  rand();
  rij.addEventListener('scroll', rand, {passive: true});
}

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
  const i = TABS.findIndex(([k]) => k === actief);
  document.querySelector('.tabbar').innerHTML =
    (i >= 0 ? `<span class="tab-lens" style="--i:${i}" aria-hidden="true"></span>` : '')
    + TABS.map(([k, href, label, svg]) =>
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
  'collecties.html': 'Collecties', 'album.html': 'Album', 'nieuwtjes.html': 'Nieuwtjes',
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
        ${rijen.map((b, i) => `
          <div title="${b.name}: ${b.value} duels" style="--i:${i}">
            <div class="bar-top num">${b.value === max ? b.value : ''}</div>
            <div class="bar-fill${b.value ? '' : ' leeg'}"
                 style="height:${b.value ? Math.max(4, b.value / max * 100) : 2}%;--i:${i}"></div>
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
    Draai <code>python3 app/build_app_data.py</code> en open deze pagina via
    <code>python3 server.py</code> op localhost:4000/app/${bestand}.</div></div>`;
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

/* ── Collecties ──────────────────────────────────────────────────────────
   Landnamen komen van de browser zelf (Intl.DisplayNames), in het Nederlands.
   Transfermarkt heeft eigen codes voor de Britse landsdelen en Kosovo. */
const LANDNAAM = {en: 'Engeland', sx: 'Schotland', wa: 'Wales', wl: 'Wales', nx: 'Noord-Ierland', xk: 'Kosovo'};
let _regio;
function landNaam(code){
  if (LANDNAAM[code]) return LANDNAAM[code];
  try {
    _regio ||= new Intl.DisplayNames(['nl'], {type: 'region'});
    return _regio.of(code.toUpperCase()) || code.toUpperCase();
  } catch { return code.toUpperCase(); }
}

/* Een meter: hoeveel van het album je al hebt. Groen op een lichtere baan van
   hetzelfde groen; het getal ernaast staat in tekstkleur. */
function meter(gezien, totaal){
  const pct = totaal ? Math.round(gezien / totaal * 100) : 0;
  return `<div class="meter" role="img" aria-label="${gezien} van ${totaal}"><i style="width:${pct}%"></i></div>`;
}

const albums = () => window.APP?.albums || [];
const album  = id => albums().find(a => a.id === id);
const albumNaam = a => a.soort === 'landen' ? `Spelers uit ${a.titel}` : `${a.titel} · ${a.groep}`;

/* Een bedrag zoals Transfermarkt het schrijft: € 15 mln, € 7,5 mln, € 450.000. */
function euro(n){
  if (n == null) return '—';
  if (n >= 1e6){
    const m = n / 1e6;
    return `€ ${m.toLocaleString('nl-NL', {maximumFractionDigits: m < 10 ? 1 : 0})} mln`;
  }
  return `€ ${n.toLocaleString('nl-NL')}`;
}

/* ── Terugkomen ──────────────────────────────────────────────────────────
   Wanneer je GroundHop op dit apparaat het laatst gebruikte. Elk scherm
   schrijft het bij openen en bij weggaan; Home leest wat er vóór dit bezoek
   stond, voor de intro na een lange afwezigheid. 0 betekent: nog nooit. Is
   er geen opslag, dan telt het als net gebruikt, zodat de intro niet bij
   elk bezoek speelt. */
function laatstGebruikt(){
  try { return Number(localStorage.getItem('gh-laatst')) || 0; } catch { return Date.now(); }
}
function gebruiktNu(){
  try { localStorage.setItem('gh-laatst', String(Date.now())); } catch {}
}
const VORIG_GEBRUIK = laatstGebruikt();
gebruiktNu();
document.addEventListener('visibilitychange', () => { if (document.hidden) gebruiktNu(); });


/* ── Beweging ────────────────────────────────────────────────────────────
   Wat in groundhop.css niet alleen kan: een teller die van het ene getal
   naar het andere rolt, het vlak van een keuzeschakelaar dat meeschuift,
   balken die pas groeien als ze in beeld komen, en verversen door Home
   omlaag te trekken. Met 'Verminder beweging' aan doet dit allemaal niets. */
const RUSTIG = matchMedia('(prefers-reduced-motion: reduce)').matches;

/* Een getal dat van van naar naar rolt. Elk cijfer dat verandert wordt een
   strookje van het oude naar het nieuwe cijfer, altijd omhoog, zoals een
   teller in een stadion; cijfers die gelijk blijven staan stil. */
function rol(van, naar){
  const a = getal(van), b = getal(naar);
  const lengte = Math.max(a.length, b.length);
  const oud = a.padStart(lengte, ' '), nieuw = b.padStart(lengte, ' ');
  return `<span class="rol" aria-label="${b}">${[...nieuw].map((c, i) => {
    const o = oud[i];
    if (o === c) return `<span aria-hidden="true">${c}</span>`;
    let stappen = [o];
    if (/\d/.test(o) && /\d/.test(c)){
      for (let d = +o; d !== +c; ) { d = (d + 1) % 10; stappen.push(String(d)); }
    } else stappen.push(c);
    return `<span class="cijfer" aria-hidden="true"><i style="--n:${stappen.length - 1}">${
      stappen.map(x => `<span>${x === ' ' ? '&nbsp;' : x}</span>`).join('')}</i></span>`;
  }).join('')}</span>`;
}

/* Een korte melding bovenaan, die vanzelf weer gaat. */
const VINKJE = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10.5l4 4 8-9"/></svg>';
function toonMelding(html, ms = 2600){
  let t = document.querySelector('.gh-toast');
  if (!t){
    t = document.createElement('div');
    t.className = 'gh-toast'; t.setAttribute('role', 'status');
    document.body.append(t);
  }
  t.innerHTML = VINKJE + html;
  requestAnimationFrame(() => t.classList.add('zien'));
  clearTimeout(toonMelding.t);
  toonMelding.t = setTimeout(() => t.classList.remove('zien'), ms);
}

/* Balken, ranglijsten en meters groeien pas als ze in beeld komen. De klasse
   'kijkt' op <html> zet ze op pauze tot dan; zonder dit script staat die er
   niet en groeien ze meteen. */
if (!RUSTIG && 'IntersectionObserver' in window){
  document.documentElement.classList.add('kijkt');
  const kijker = new IntersectionObserver(items => items.forEach(x => {
    if (x.isIntersecting){ x.target.classList.add('in-beeld'); kijker.unobserve(x.target); }
  }), {rootMargin: '0px 0px -8% 0px'});
  const zoek = wortel => wortel.querySelectorAll?.('.chart, .rank, .meter').forEach(el => {
    if (!el.classList.contains('in-beeld')) kijker.observe(el);
  });
  new MutationObserver(lijst => lijst.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType !== 1) return;
    if (n.matches('.chart, .rank, .meter')) kijker.observe(n);
    zoek(n);
  }))).observe(document.documentElement, {childList: true, subtree: true});
  document.addEventListener('DOMContentLoaded', () => zoek(document));
  zoek(document);
}

/* Een keuzeschakelaar wordt bij elke keuze opnieuw getekend. Onthoud waar het
   witte vlak stond, en laat een los vlak van daar naar de nieuwe keuze
   schuiven zodra het scherm opnieuw getekend is. */
const groepSleutel = g => (g.getAttribute('aria-label') || '') + '|'
  + [...g.querySelectorAll('button')].map(b => b.textContent.trim()).join('|');
document.addEventListener('click', e => {
  if (RUSTIG) return;
  const knop = e.target.closest('.seg button, .chips button');
  if (!knop) return;
  const groep = knop.parentElement, oud = groep.querySelector('[aria-pressed="true"]');
  if (!oud || oud === knop) return;
  const g = groep.getBoundingClientRect(), o = oud.getBoundingClientRect();
  const van = {sleutel: groepSleutel(groep), links: o.left - g.left + groep.scrollLeft, breed: o.width};
  requestAnimationFrame(() => {
    const nieuw = [...document.querySelectorAll('.seg, .chips')].find(x => groepSleutel(x) === van.sleutel);
    const keuze = nieuw && nieuw.querySelector('[aria-pressed="true"]');
    if (!keuze) return;
    const g2 = nieuw.getBoundingClientRect(), k = keuze.getBoundingClientRect();
    const links = k.left - g2.left + nieuw.scrollLeft;
    const pil = document.createElement('i');
    pil.className = 'seg-pil';
    pil.style.cssText = `left:${links}px; width:${k.width}px;`;
    nieuw.classList.add('pil-loopt');
    nieuw.prepend(pil);
    const anim = pil.animate([
      {transform: `translateX(${van.links - links}px)`, width: `${van.breed}px`},
      {transform: 'none', width: `${k.width}px`},
    ], {duration: 280, easing: 'cubic-bezier(.2,.8,.2,1)'});
    const klaar = () => { pil.remove(); nieuw.classList.remove('pil-loopt'); };
    anim.onfinish = klaar; anim.oncancel = klaar;
  });
}, true);

/* ── Verversen ───────────────────────────────────────────────────────────
   Op het beginscherm heeft de app geen browser om te verversen. Trek een
   scherm omlaag: de bal uit de intro komt mee, hopt terwijl de pagina
   opnieuw laadt, en daarna zegt een melding (of op Home de pop-up) wat er
   nieuw is. */
const BAL_SVG = `<svg class="gh-bal" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9"/>
  <path d="M10 6.2 13.61 8.83 12.23 13.07H7.77L6.39 8.83z"/>
  <path d="M10 6.2V1M13.61 8.83l4.95-1.61M12.23 13.07l3.06 4.21M7.77 13.07l-3.06 4.21M6.39 8.83l-4.95-1.61"/></svg>`;
let VERVERST = false;
try {
  const t = Number(sessionStorage.getItem('gh-ververst'));
  VERVERST = t > 0 && Date.now() - t < 20000;
  sessionStorage.removeItem('gh-ververst');
} catch {}

function trekOmTeVerversen(){
  const main = document.querySelector('main');
  if (!main || !('ontouchstart' in window)) return;
  const bal = document.createElement('div');
  bal.className = 'ververs';
  bal.innerHTML = BAL_SVG;
  document.body.append(bal);
  const DREMPEL = 72, MAX = 110;
  let start = null, afstand = 0, bezig = false;
  const zet = y => {
    main.style.transform = y ? `translateY(${y}px)` : '';
    bal.style.opacity = Math.min(1, y / DREMPEL);
    bal.style.transform = `scale(${0.5 + Math.min(1, y / DREMPEL) / 2}) rotate(${y * 4}deg)`;
  };
  main.addEventListener('touchstart', e => {
    start = !bezig && main.scrollTop <= 0 && e.touches.length === 1 ? e.touches[0].clientY : null;
    afstand = 0;
    main.classList.remove('veert');
  }, {passive: true});
  main.addEventListener('touchmove', e => {
    if (start == null) return;
    const dy = e.touches[0].clientY - start;
    if (dy <= 0){ zet(0); afstand = 0; return; }
    e.preventDefault();
    afstand = Math.min(MAX, dy * 0.5);
    zet(afstand);
  }, {passive: false});
  main.addEventListener('touchend', () => {
    if (start == null) return;
    start = null;
    main.classList.add('veert');
    if (afstand >= DREMPEL){
      bezig = true;
      zet(DREMPEL * 0.8);
      bal.style.transform = '';
      bal.classList.add('hopt');
      try { sessionStorage.setItem('gh-ververst', String(Date.now())); } catch {}
      setTimeout(() => location.reload(), 650);
    } else zet(0);
  });
}
