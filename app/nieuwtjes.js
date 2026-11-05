/* GroundHop — nieuwtjes: wat elk duel jou opleverde.

   Alles wordt hier opnieuw uitgerekend, op datum, uit APP en SPELERS. Een
   nieuwtje is het verschil tussen vóór en na een duel: je eerste speler uit
   Gabon, goal nr. 700, PSV die voor het eerst in negen duels verliest. Voeg
   je later een duel uit 2019 toe, dan krijgt dat duel de nieuwtjes van toen
   en kan een mijlpaal naar een ander duel schuiven. Er wordt niets bewaard,
   dus het klopt altijd met de data die er nu staat.

   Elk nieuwtje heeft een gewicht. Groot is zeldzaam en gaat altijd voor,
   Gewoon krijgt een zin als er plek is, Klein is een feitje onderaan. Binnen
   een gewicht gaat het zeldzaamste voor: hoe vaak een soort in jouw eigen
   duels voorkwam, bepaalt de volgorde.

   Werkt in de browser (na groundhop.js) en in node, voor de toets in test/.
*/
(function(root){
'use strict';

/* Afstanden worden gemeten vanaf thuis, het dorpshart van Grubbenvorst. */
const THUIS = {naam: 'Grubbenvorst', lat: 51.421, lon: 6.146};

/* De getallen waarbij een mijlpaal verschijnt. */
const DREMPEL = {
  speler:      [25, 50, 75, 100, 150, 200, 250],
  spelerGoals: [10, 25, 50, 75, 100, 150],
  ground:      [10, 25, 50, 75, 100, 125, 150, 200, 250, 300],
  club:        [10, 25, 50, 100, 125, 150, 200, 250, 300],
};
const isDuelDrempel = n => n === 1 || n === 10 || n === 25 || (n >= 50 && n % 25 === 0);
const volgendeDuel = n => n < 1 ? 1 : n < 10 ? 10 : n < 25 ? 25 : n < 50 ? 50 : (Math.floor(n / 25) + 1) * 25;
const vorigeDuel = n => n >= 50 ? Math.floor(n / 25) * 25 : n >= 25 ? 25 : n >= 10 ? 10 : n >= 1 ? 1 : 0;
const volgendeUit = (lijst, n) => lijst.find(d => d > n);
const vorigeUit = (lijst, n) => [...lijst].reverse().find(d => d <= n) || 0;

/* Lange reeksen: hoe lang een reeks met jou erbij moet zijn om te melden. */
const REEKS_ONGESLAGEN = 8, REEKS_NEDERLAGEN = 3;
/* Een record telt pas na een paar duels; je derde duel is geen record. */
const RECORD_VANAF = 6;
/* Eindelijk een goal: na minstens zoveel duels op het veld. */
const EINDELIJK = 15;

const GEWICHT = {groot: 0, gewoon: 1, klein: 2};
/* Feitjes in deze volgorde: wat het meest over dit duel zegt eerst. */
const FEITJE = ['nieuwe-spelers', 'eerste-goals', 'landen-veld', 'publiek', 'duurste', 'eigen-goal',
                'onderling', 'bezoek', 'basiself', 'duels-seizoen'];

/* Per soort: het gewicht, het icoon en in welke filters van het logboek hij
   valt. */
const SOORT = {
  'duel-mijlpaal':     ['groot',  'ster',     ['mijlpalen']],
  'goal-mijlpaal':     ['groot',  'bal',      ['mijlpalen']],
  'recordseizoen':     ['groot',  'kalender', ['mijlpalen']],
  'nieuwe-ground':     ['groot',  'stadion',  ['grounds']],
  'nieuw-land-ground': ['groot',  'wereld',   ['grounds', 'landen']],
  'verste-ground':     ['groot',  'wereld',   ['grounds']],
  'ground-mijlpaal':   ['gewoon', 'stadion',  ['grounds', 'mijlpalen']],
  'publiek-ground':    ['gewoon', 'publiek',  ['grounds']],
  'nieuwe-club':       ['gewoon', 'schild',   ['clubs']],
  'reeks-voorbij':     ['groot',  'reeks',    ['clubs', 'wedstrijden']],
  'club-mijlpaal':     ['gewoon', 'schild',   ['clubs', 'mijlpalen']],
  'nieuwe-competitie': ['gewoon', 'beker',    ['clubs']],
  'nieuwe-topscorer':  ['groot',  'kroon',    ['spelers']],
  'eindelijk-goal':    ['groot',  'bal',      ['spelers']],
  'hattrick':          ['groot',  'bal',      ['spelers', 'wedstrijden']],
  'goals-speler':      ['gewoon', 'bal',      ['spelers', 'mijlpalen']],
  'vaakst-gezien':     ['groot',  'persoon',  ['spelers']],
  'speler-mijlpaal':   ['gewoon', 'persoon',  ['spelers', 'mijlpalen']],
  'assistkoning':      ['gewoon', 'kroon',    ['spelers']],
  'nieuw-land-speler': ['groot',  'vlag',     ['landen', 'spelers']],
  'jongste':           ['groot',  'persoon',  ['spelers']],
  'oudste':            ['groot',  'persoon',  ['spelers']],
  'landen-record':     ['groot',  'vlag',     ['landen', 'wedstrijden']],
  'record-goals':      ['groot',  'beker',    ['wedstrijden']],
  'record-zege':       ['groot',  'beker',    ['wedstrijden']],
  'record-publiek':    ['groot',  'publiek',  ['wedstrijden']],
  'comeback':          ['groot',  'keer',     ['wedstrijden']],
  'late-winnaar':      ['groot',  'klok',     ['wedstrijden']],
  'strafschoppen':     ['groot',  'goal',     ['wedstrijden']],
  'goalfeest':         ['gewoon', 'bal',      ['wedstrijden']],
  'nul-nul':           ['gewoon', 'nul',      ['wedstrijden']],
  'rode-kaart':        ['gewoon', 'kaart',    ['wedstrijden', 'spelers']],
  'album-compleet':    ['groot',  'album',    ['mijlpalen']],
  // Klein: feitjes.
  'duels-seizoen':     ['klein'], 'bezoek':      ['klein'], 'onderling':    ['klein'],
  'nieuwe-spelers':    ['klein'], 'eerste-goals': ['klein'], 'landen-veld': ['klein'],
  'duurste':           ['klein'], 'basiself':    ['klein'], 'eigen-goal':   ['klein'],
  'publiek':           ['klein'],
};

/* ── Hulpjes. In de browser staan de meeste al in groundhop.js; in node
   niet, dus hier een eigen versie. */
const esc = t => String(t ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const getal = n => n == null ? '—' : Number(n).toLocaleString('nl-NL');
const KORT = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];
const MND = ['januari','februari','maart','april','mei','juni','juli','augustus',
             'september','oktober','november','december'];
const kortDatum = iso => { const [j, m, d] = iso.split('-'); return `${+d} ${KORT[+m - 1]} ${j}`; };
const dagMaand = iso => { const [, m, d] = iso.split('-'); return `${+d} ${MND[+m - 1]}`; };
const seizoenLabel = j => `${String(j).slice(2)}/${String(j + 1).slice(2)}`;
const LANDNAAM = {en: 'Engeland', sx: 'Schotland', wa: 'Wales', wl: 'Wales', nx: 'Noord-Ierland', xk: 'Kosovo'};
let _regio;
function landNaam(code){
  if (typeof root.landNaam === 'function') return root.landNaam(code);
  if (LANDNAAM[code]) return LANDNAAM[code];
  try {
    _regio ||= new Intl.DisplayNames(['nl'], {type: 'region'});
    return _regio.of(code.toUpperCase()) || code.toUpperCase();
  } catch { return code.toUpperCase(); }
}
function euro(n){
  if (n >= 1e6){
    const m = n / 1e6;
    return `€ ${m.toLocaleString('nl-NL', {maximumFractionDigits: m < 10 ? 1 : 0})} mln`;
  }
  return `€ ${n.toLocaleString('nl-NL')}`;
}
const km = (a, b) => {
  const r = g => g * Math.PI / 180;
  const h = Math.sin((r(b.lat) - r(a.lat)) / 2) ** 2
          + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin((r(b.lon) - r(a.lon)) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
};
const minuut = (min, add) => add ? `${min}+${add}` : `${min}`;
const kortAlbum = a => a.soort === 'landen' ? a.titel : `${a.groep.replace(/ \d{4}\/\d{2}$/, '')} · ${a.titel}`;
const H = {
  wedstrijd: id => `wedstrijddetail.html#id=${id}`,
  speler:    id => `speler.html#id=${id}`,
  club:      id => `club.html#id=${id}`,
  stadion:   k  => `stadiondetail.html#v=${encodeURIComponent(k)}`,
  comp:      t  => `competitie.html#t=${encodeURIComponent(t)}`,
  album:     id => `album.html#id=${encodeURIComponent(id)}`,
};
const b = t => `<b>${esc(t)}</b>`;
const em = t => `<em>${t}</em>`;
const _geboren = {};
function leeftijd(dob, op){
  const a = _geboren[dob] ||= new Date(dob.slice(0, 10) + 'T12:00:00'), z = new Date(op + 'T12:00:00');
  let j = z.getFullYear() - a.getFullYear();
  const jarig = new Date(a); jarig.setFullYear(z.getFullYear());
  if (jarig > z){ j--; jarig.setFullYear(z.getFullYear() - 1); }
  return {jaren: j, dagen: Math.round((z - jarig) / 864e5), totaal: Math.round((z - a) / 864e5)};
}

/* ── De berekening ───────────────────────────────────────────────────── */
function bereken(APP, SPELERS){
  const clubs = {}; APP.clubs.forEach(c => clubs[c.id] = c);
  const venues = {}; APP.venues.forEach(v => venues[v.key] = v);
  const naamClub = id => (clubs[id] || {}).name || '?';
  const M = APP.matches.slice().reverse();          // oudste eerst
  const volgnr = {}; M.forEach((m, i) => volgnr[m.id] = i);

  // Per duel de spelers die erbij waren, ook op de bank.
  const perDuel = {};
  for (const [id, p] of Object.entries(SPELERS)){
    for (const r of p.m || []){
      (perDuel[r[0]] ||= []).push({id, p, team: r[1], min: r[2] || 0, g: r[3] || 0, a: r[4] || 0,
                                   basis: !!r[5], veld: !!r[5] || (r[2] || 0) > 0});
    }
  }

  // Collecties: welk album hoort bij welke club, ground of land.
  const albumVan = {club: {}, ground: {}, land: {}};
  const albumStand = {};
  for (const a of APP.albums || []){
    albumStand[a.id] = 0;
    for (const i of a.items){
      const [soort, sleutel] = a.soort === 'clubs' ? ['club', i.club]
        : a.soort === 'stadions' ? ['ground', i.key] : ['land', i.code];
      if (sleutel != null) (albumVan[soort][sleutel] ||= []).push(a);
    }
  }
  // Een stap in een collectie: geeft de eerste album-meter terug, en een
  // nieuwtje als dat album daarmee vol is.
  function albumStap(soort, sleutel, uit, m){
    let meter = null;
    for (const a of albumVan[soort][sleutel] || []){
      const x = ++albumStand[a.id];
      meter ||= {x, totaal: a.items.length, naam: kortAlbum(a), id: a.id};
      if (x === a.items.length){
        uit.push(z('album-compleet', `Album compleet: ${b(kortAlbum(a))}`,
          `${a.items.length} van ${a.items.length}`, H.album(a.id)));
      }
    }
    return meter;
  }

  const S = {
    duels: 0, goals: 0, seizoen: {}, recordSeizoen: new Set(),
    ground: {}, groundAtt: {}, landGround: new Set(), verste: null,
    club: {}, comp: new Set(), paar: {}, reeks: {},
    gezien: {}, veld: {}, goalsSp: {}, assists: {}, landSp: new Set(),
    top: null, topGezien: null, topAssist: null, jongste: null, oudste: null,
    recGoals: null, recZege: null, recAtt: null, recNat: null,
    rood: 0, hattricks: 0, nulnul: 0, goalfeest: 0, pens: 0,
  };
  const per = {};

  const metMeter = a => a ? {meter: [a.x, a.totaal], meterTekst: `${esc(a.naam)}: ${a.x} van ${a.totaal}`} : null;

  // Een nieuwtje. Gewicht en icoon volgen uit de soort.
  function z(soort, tekst, sub, href, extra){
    const [gewicht, ico, cats] = SOORT[soort];
    return Object.assign({soort, gewicht, ico, cats: cats || [], tekst, sub: sub || '', href: href || null}, extra || {});
  }

  for (const m of M){
    const uit = [];
    const thuisNaam = naamClub(m.hid), uitNaam = naamClub(m.aid);
    const v = m.venue ? venues[m.venue] : null;
    const spelers = perDuel[m.id] || [];

    // ── Jouw verzameling
    S.duels++;
    if (isDuelDrempel(S.duels)){
      const vlg = volgendeDuel(S.duels);
      uit.push(z('duel-mijlpaal', S.duels === 1 ? 'Je eerste duel' : `Je ${em(S.duels + 'e')} duel`,
        `Volgende: ${vlg} · nog ${vlg - S.duels}`, H.wedstrijd(m.id)));
    }
    for (const g of m.goals){
      S.goals++;
      if (S.goals % 100 === 0){
        uit.push(z('goal-mijlpaal', `Goal ${em('nr. ' + getal(S.goals))} die je zag`,
          `${esc(g.p || '?')}, ${minuut(g.min, g.add)}e minuut · volgende: ${getal(S.goals + 100)}`,
          g.pid && SPELERS[g.pid] ? H.speler(g.pid) : H.wedstrijd(m.id)));
      }
    }
    const sz = m.season;
    S.seizoen[sz] = (S.seizoen[sz] || 0) + 1;
    const nSz = S.seizoen[sz];
    let best = 0, bestSz = null;
    for (const [j, n] of Object.entries(S.seizoen)) if (+j !== sz && n > best){ best = n; bestSz = +j; }
    if (nSz === best + 1 && best >= 5 && !S.recordSeizoen.has(sz)){
      S.recordSeizoen.add(sz);
      uit.push(z('recordseizoen', `Je ${em(nSz + 'e')} duel van ${seizoenLabel(sz)}: nooit zag je er meer in één seizoen`,
        `Het vorige record: ${best}, in ${seizoenLabel(bestSz)}`, 'duels.html'));
    }
    uit.push(z('duels-seizoen', `Je ${b(nSz + 'e')} duel van ${seizoenLabel(sz)}`));

    // ── Grounds
    if (m.venue){
      const naam = v ? v.name : m.venue;
      const nieuw = !S.ground[m.venue];
      S.ground[m.venue] = (S.ground[m.venue] || 0) + 1;
      const k = S.ground[m.venue];
      const afstand = v && v.lat != null ? Math.round(km(THUIS, v)) : null;
      if (nieuw){
        const nr = Object.keys(S.ground).length;
        const meter = albumStap('ground', m.venue, uit, m);
        const delen = [v && v.city ? esc(v.city) : null, `ground nr. ${nr}`,
          afstand != null ? `${getal(afstand)} km van ${THUIS.naam}` : null].filter(Boolean);
        uit.push(z('nieuwe-ground', `Nieuwe ground: ${b(naam)}`, delen.join(' · '), H.stadion(m.venue),
          metMeter(meter)));
        if (afstand != null){
          if (S.verste && afstand > S.verste.km){
            uit.push(z('verste-ground', `Je verste ground tot nu toe: ${em(getal(afstand) + ' km')}`,
              `${esc(naam)}, gemeten vanaf ${THUIS.naam}`, H.stadion(m.venue)));
          }
          if (!S.verste || afstand > S.verste.km) S.verste = {km: afstand, naam};
        }
      }
      if (v && v.country && !S.landGround.has(v.country)){
        if (S.landGround.size) uit.push(z('nieuw-land-ground', `Je eerste duel in ${b(v.country)}`,
          `${esc(naam)}${v.city ? ', ' + esc(v.city) : ''}`, H.stadion(m.venue)));
        S.landGround.add(v.country);
      }
      if (DREMPEL.ground.includes(k)){
        uit.push(z('ground-mijlpaal', `Je ${em(k + 'e')} bezoek aan ${b(naam)}`,
          v && v.first ? `Het eerste: ${dagMaand(v.first)} ${v.first.slice(0, 4)}` : '', H.stadion(m.venue)));
      }
      if (m.att){
        const vorig = S.groundAtt[m.venue];
        if (vorig && k >= 4 && m.att > vorig){
          uit.push(z('publiek-ground', `Nooit zag je meer publiek in ${b(naam)}: ${em(getal(m.att))}`,
            `Vorig record: ${getal(vorig)}`, H.stadion(m.venue)));
        }
        S.groundAtt[m.venue] = Math.max(vorig || 0, m.att);
      }
      if (k > 1) uit.push(z('bezoek', `${b(k + 'e')} bezoek ${esc(naam)}`));
    }

    // ── Clubs en competities
    for (const id of [m.hid, m.aid]){
      if (!S.club[id]){
        const nr = Object.keys(S.club).length + 1;
        const meter = albumStap('club', id, uit, m);
        uit.push(z('nieuwe-club', `Nieuwe club: ${b(naamClub(id))}`, `Club nr. ${nr}`, H.club(id), metMeter(meter)));
      }
      S.club[id] = (S.club[id] || 0) + 1;
      if (DREMPEL.club.includes(S.club[id])){
        uit.push(z('club-mijlpaal', `${b(naamClub(id))} voor de ${em(S.club[id] + 'e')} keer`, '', H.club(id)));
      }
    }
    if (!S.comp.has(m.t)){
      S.comp.add(m.t);
      if (S.comp.size > 1) uit.push(z('nieuwe-competitie', `Je eerste duel in de ${b(m.t)}`,
        `Competitie nr. ${S.comp.size}`, H.comp(m.t)));
    }
    const paar = [m.hid, m.aid].sort((x, y) => x - y).join('-');
    S.paar[paar] = (S.paar[paar] || 0) + 1;
    if (S.paar[paar] > 1) uit.push(z('onderling', `${b(S.paar[paar] + 'e')} keer ${esc(thuisNaam)} – ${esc(uitNaam)}`));

    // ── De wedstrijd
    const metStand = m.hs != null && m.as != null;
    if (metStand){
      // Reeksen per club: ongeslagen, of nederlagen op rij, met jou erbij.
      for (const [id, voor, tegen, tegenstander] of [[m.hid, m.hs, m.as, m.aid], [m.aid, m.as, m.hs, m.hid]]){
        const r = S.reeks[id] ||= {ongeslagen: 0, nederlagen: 0, laatste: null};
        // Een strafschoppenserie verliezen is in de uitslag een gelijkspel.
        if (voor < tegen){
          if (r.ongeslagen >= REEKS_ONGESLAGEN){
            const l = r.laatste;
            uit.push(z('reeks-voorbij', `${b(naamClub(id))} verloor voor het eerst in ${em(r.ongeslagen + 1)} duels met jou erbij`,
              l ? `Vorige nederlaag: ${l.score} tegen ${esc(l.tegen)}, ${dagMaand(l.datum)}${l.datum.slice(0, 4) === m.date.slice(0, 4) ? '' : ' ' + l.datum.slice(0, 4)}`
                : 'Nooit eerder verloren met jou erbij', H.club(id)));
          }
          r.ongeslagen = 0; r.nederlagen++;
          r.laatste = {score: `${voor}–${tegen}`, tegen: naamClub(tegenstander), datum: m.date};
        } else {
          if (r.nederlagen >= REEKS_NEDERLAGEN){
            uit.push(z('reeks-voorbij', `${b(naamClub(id))} ${voor > tegen ? 'wint weer' : 'verliest niet'}, na ${em(r.nederlagen)} nederlagen op rij met jou erbij`,
              '', H.club(id)));
          }
          r.nederlagen = 0; r.ongeslagen++;
        }
      }
      // Records over al je duels.
      const som = m.hs + m.as, verschil = Math.abs(m.hs - m.as);
      let recordGoals = false;
      if (S.duels >= RECORD_VANAF && S.recGoals && som > S.recGoals.n){
        recordGoals = true;
        const ookZege = S.recZege && verschil > S.recZege.n;
        uit.push(z('record-goals', `Meeste goals in één duel ooit: ${em(som)}`,
          ookZege ? 'En meteen je grootste zege' : `Vorig record: ${S.recGoals.n}`, H.wedstrijd(m.id)));
      }
      if (S.duels >= RECORD_VANAF && S.recZege && verschil > S.recZege.n && !recordGoals){
        uit.push(z('record-zege', `Grootste zege ooit: ${em(`${m.hs}–${m.as}`)}`,
          `Vorig record: ${S.recZege.n} goals verschil`, H.wedstrijd(m.id)));
      }
      if (!S.recGoals || som > S.recGoals.n) S.recGoals = {n: som};
      if (!S.recZege || verschil > S.recZege.n) S.recZege = {n: verschil};
      if (som >= 7 && !recordGoals){
        S.goalfeest++;
        uit.push(z('goalfeest', `${em(som)} goals in één duel`,
          S.goalfeest === 1 ? 'De eerste keer zeven of meer' : `Je ${S.goalfeest}e keer zeven of meer`, H.wedstrijd(m.id)));
      } else if (som >= 7) S.goalfeest++;
      if (som === 0){
        S.nulnul++;
        uit.push(z('nul-nul', S.nulnul === 1 ? 'Je eerste 0–0' : `Een 0–0, je ${em(S.nulnul + 'e')} ooit`, '', H.wedstrijd(m.id)));
      }
      // Comeback: een ploeg stond twee achter en verloor niet.
      let h = 0, a = 0; const diep = {h: null, a: null};
      for (const g of m.goals){
        if (g.team === thuisNaam) h++; else if (g.team === uitNaam) a++;
        if (a - h >= 2 && (!diep.h || a - h > diep.h.d)) diep.h = {d: a - h, s: `${h}–${a}`};
        if (h - a >= 2 && (!diep.a || h - a > diep.a.d)) diep.a = {d: h - a, s: `${h}–${a}`};
      }
      if (diep.h && m.hs >= m.as) uit.push(z('comeback', `Comeback: ${b(thuisNaam)} van ${diep.h.s} naar ${m.hs}–${m.as}`, '', H.wedstrijd(m.id)));
      if (diep.a && m.as >= m.hs) uit.push(z('comeback', `Comeback: ${b(uitNaam)} van ${diep.a.s} naar ${m.hs}–${m.as}`, '', H.wedstrijd(m.id)));
      // Late winnaar: de goal die de winnaar voorgoed op voorsprong zette.
      if (m.hs !== m.as){
        const winnaar = m.hs > m.as ? thuisNaam : uitNaam;
        const nodig = Math.min(m.hs, m.as) + 1;
        const beslissend = m.goals.filter(g => g.team === winnaar)[nodig - 1];
        if (beslissend && beslissend.min >= 90){
          uit.push(z('late-winnaar', `Winnende goal in de ${em(minuut(beslissend.min, beslissend.add) + 'e')} minuut: ${b(beslissend.p || '?')}`,
            esc(winnaar), beslissend.pid && SPELERS[beslissend.pid] ? H.speler(beslissend.pid) : H.wedstrijd(m.id)));
        }
      }
    }
    if (m.pen){
      S.pens++;
      const winnaar = m.pen[0] > m.pen[1] ? thuisNaam : uitNaam;
      uit.push(z('strafschoppen', `Strafschoppen: ${b(winnaar)} wint met ${em(`${Math.max(...m.pen)}–${Math.min(...m.pen)}`)}`,
        S.pens === 1 ? 'Je eerste strafschoppenserie' : `Je ${S.pens}e strafschoppenserie`, H.wedstrijd(m.id)));
    }
    if (m.att){
      if (S.duels >= RECORD_VANAF && S.recAtt && m.att > S.recAtt.n){
        uit.push(z('record-publiek', `Meeste publiek ooit: ${em(getal(m.att))}`,
          v ? esc(v.name) + (v.city ? ', ' + esc(v.city) : '') : `Vorig record: ${getal(S.recAtt.n)}`, H.wedstrijd(m.id)));
      }
      if (!S.recAtt || m.att > S.recAtt.n) S.recAtt = {n: m.att};
      uit.push(z('publiek', `${b(getal(m.att))} publiek`));
    }
    for (const k of m.cards || []){
      if (k.type !== 'rood' && k.type !== 'geelrood') continue;
      S.rood++;
      uit.push(z('rode-kaart', k.type === 'geelrood' ? `Twee keer geel voor ${b(k.p || '?')}` : `Rood voor ${b(k.p || '?')}`,
        `De ${S.rood}e rode kaart die je zag`, H.wedstrijd(m.id)));
    }
    for (const g of m.goals) if (g.type === 'own' || g.type === 'ownGoal'){
      uit.push(z('eigen-goal', `Eigen goal van ${b(g.p || '?')}`));
    }

    // ── Spelers
    let nieuweSpelers = 0; const nieuwPerTeam = {};
    const eersteGoal = [];
    const landKandidaat = {};
    let duurste = null;
    for (const s of spelers){
      const {id, p} = s;
      if (!S.gezien[id]){ nieuweSpelers++; nieuwPerTeam[s.team] = (nieuwPerTeam[s.team] || 0) + 1; }
      S.gezien[id] = (S.gezien[id] || 0) + 1;
      if (DREMPEL.speler.includes(S.gezien[id])){
        uit.push(z('speler-mijlpaal', `${b(p.n)}: ${em(S.gezien[id])} keer gezien`, '', H.speler(id)));
      }
      if (s.veld) S.veld[id] = (S.veld[id] || 0) + 1;
      const voor = S.goalsSp[id] || 0;
      if (s.g){
        S.goalsSp[id] = voor + s.g;
        if (!voor){
          eersteGoal.push(s);
          if ((S.veld[id] || 0) >= EINDELIJK){
            uit.push(z('eindelijk-goal', `Na ${em(S.veld[id])} duels eindelijk een goal van ${b(p.n)}`, '', H.speler(id)));
          }
        }
        if (s.g >= 3){
          S.hattricks++;
          uit.push(z('hattrick', s.g === 3 ? `Hattrick van ${b(p.n)}` : `${em(s.g)} goals van ${b(p.n)}`,
            (voor ? '' : 'Meteen zijn eerste goals waar jij bij was · ')
            + (S.hattricks === 1 ? 'je eerste hattrick' : `je ${S.hattricks}e hattrick`), H.speler(id)));
        }
        const drempel = DREMPEL.spelerGoals.find(d => voor < d && voor + s.g >= d);
        if (drempel){
          uit.push(z('goals-speler', `${b(p.n)}: zijn ${em(drempel + 'e')} goal waar jij bij was`, '', H.speler(id)));
        }
      }
      if (s.a) S.assists[id] = (S.assists[id] || 0) + s.a;
      if (s.veld && p.c && !S.landSp.has(p.c)){
        const k = landKandidaat[p.c];
        if (!k || s.min > k.min) landKandidaat[p.c] = s;
      }
      if (s.veld && p.mv && (!duurste || p.mv > duurste.p.mv)) duurste = s;
      if (s.veld && p.dob && S.duels >= 1){
        const l = leeftijd(p.dob, m.date);
        if (S.duels >= RECORD_VANAF && S.jongste && l.totaal < S.jongste.dagen && S.jongste.id !== id){
          uit.push(z('jongste', `Jongste speler die je ooit zag: ${b(p.n)}, ${em(l.jaren)} jaar en ${l.dagen} dagen`,
            `Vorige: ${esc(S.jongste.naam)}`, H.speler(id)));
        }
        if (S.duels >= RECORD_VANAF && S.oudste && l.totaal > S.oudste.dagen && S.oudste.id !== id){
          uit.push(z('oudste', `Oudste speler die je ooit zag: ${b(p.n)}, ${em(l.jaren)} jaar en ${l.dagen} dagen`,
            `Vorige: ${esc(S.oudste.naam)}`, H.speler(id)));
        }
        if (!S.jongste || l.totaal < S.jongste.dagen) S.jongste = {dagen: l.totaal, id, naam: p.n};
        if (!S.oudste || l.totaal > S.oudste.dagen) S.oudste = {dagen: l.totaal, id, naam: p.n};
      }
    }
    for (const [code, s] of Object.entries(landKandidaat)){
      S.landSp.add(code);
      if (S.duels === 1) continue;    // je eerste duel: alles is nieuw
      const meter = albumStap('land', code, uit, m);
      uit.push(z('nieuw-land-speler', `Voor het eerst een speler uit ${b(landNaam(code))}: ${esc(s.p.n)}`,
        `${esc(s.team)} · land nr. ${S.landSp.size}`, H.speler(s.id), metMeter(meter)));
    }
    if (S.duels === 1){
      // De collecties beginnen ook bij je eerste duel.
      for (const code of Object.keys(landKandidaat)) albumStap('land', code, [], m);
    }
    // Ranglijsten: wie is nu de nummer 1? Alleen wie er strikt overheen gaat.
    // Alleen de spelers van dit duel kunnen gestegen zijn, dus de nummer 1 is
    // de huidige of een van hen. Gelijk komen is niet genoeg.
    const nummer1 = (teller, huidig) => {
      let beste = huidig ? {id: huidig.id, n: teller[huidig.id] || 0} : null;
      for (const s of spelers){
        const n = teller[s.id] || 0;
        if (n > 0 && (!beste || n > beste.n)) beste = {id: s.id, n};
      }
      return beste;
    };
    const top = nummer1(S.goalsSp, S.top);
    if (S.top && top && top.id !== S.top.id){
      uit.push(z('nieuwe-topscorer', `Nieuwe nummer 1 van je topscorers: ${b(SPELERS[top.id].n)}, ${em(top.n)} goals`,
        `Neemt het over van ${esc(SPELERS[S.top.id].n)}`, H.speler(top.id)));
    }
    S.top = top;
    const topG = nummer1(S.gezien, S.topGezien);
    if (S.topGezien && topG && topG.id !== S.topGezien.id){
      uit.push(z('vaakst-gezien', `${b(SPELERS[topG.id].n)} is nu je vaakst geziene speler: ${em(topG.n)} duels`,
        `Neemt het over van ${esc(SPELERS[S.topGezien.id].n)}`, H.speler(topG.id)));
    }
    S.topGezien = topG;
    const topA = nummer1(S.assists, S.topAssist);
    if (S.topAssist && topA && topA.id !== S.topAssist.id){
      uit.push(z('assistkoning', `${b(SPELERS[topA.id].n)} is je nieuwe assistkoning: ${em(topA.n)} assists`,
        `Neemt het over van ${esc(SPELERS[S.topAssist.id].n)}`, H.speler(topA.id)));
    }
    S.topAssist = topA;

    if (S.duels > 1 && nieuweSpelers){
      const teams = Object.keys(nieuwPerTeam);
      uit.push(z('nieuwe-spelers', `${b(nieuweSpelers)} ${nieuweSpelers === 1 ? 'speler' : 'spelers'} die je nog nooit zag`
        + (teams.length === 1 && nieuweSpelers > 1 ? `, allemaal van ${esc(teams[0])}` : '')));
    }
    if (eersteGoal.length === 1) uit.push(z('eerste-goals', `${b(eersteGoal[0].p.n)} zag je voor het eerst scoren`));
    else if (eersteGoal.length > 1) uit.push(z('eerste-goals', `${b(eersteGoal.length)} spelers zag je voor het eerst scoren`));
    if (m.nat){
      if (S.duels >= RECORD_VANAF && S.recNat && m.nat > S.recNat.n){
        uit.push(z('landen-record', `${em(m.nat)} landen op het veld: nooit zag je er meer`,
          `Vorig record: ${S.recNat.n}, bij ${esc(S.recNat.duel)}`, H.wedstrijd(m.id)));
      } else uit.push(z('landen-veld', `${b(m.nat)} landen op het veld`));
      if (!S.recNat || m.nat > S.recNat.n) S.recNat = {n: m.nat, duel: `${thuisNaam} – ${uitNaam}`};
    }
    if (duurste) uit.push(z('duurste', `Duurste op het veld: ${b(duurste.p.n)}, ${euro(duurste.p.mv)}`));
    if (m.elf && m.elf.length){
      const j = x => x.toLocaleString('nl-NL', {minimumFractionDigits: 1, maximumFractionDigits: 1});
      uit.push(z('basiself', 'Basiself ' + m.elf.map(([t, x], i) => i === 0 ? `${esc(t)} ${b(j(x))} jaar` : `${esc(t)} ${b(j(x))}`).join(', ')));
    }

    per[m.id] = uit.map(x => Object.assign(x, {duel: m.id}));
  }

  // Hoe vaak elke soort voorkwam: het zeldzaamste gaat voor.
  const vaak = {};
  for (const lijst of Object.values(per)) for (const x of lijst) vaak[x.soort] = (vaak[x.soort] || 0) + 1;
  const orde = (x, y) => (GEWICHT[x.gewicht] - GEWICHT[y.gewicht]) || ((vaak[x.soort] || 0) - (vaak[y.soort] || 0));

  return {
    THUIS, vaak, volgnr,
    /* Zinnen (groot en gewoon) en feitjes (klein) van één duel, in volgorde. */
    van(id){
      const lijst = (per[id] || []).slice();
      return {zinnen: lijst.filter(x => x.gewicht !== 'klein').sort(orde),
              feitjes: lijst.filter(x => x.gewicht === 'klein')
                .sort((x, y) => FEITJE.indexOf(x.soort) - FEITJE.indexOf(y.soort))};
    },
    /* De zinnen van een paar duels samen, gesorteerd over alle duels. */
    samen(ids){
      const lijst = ids.flatMap(id => (per[id] || []).filter(x => x.gewicht !== 'klein'));
      return lijst.sort((x, y) => orde(x, y) || (volgnr[y.duel] - volgnr[x.duel]));
    },
    /* Wat er bij kwam met deze duels: tellers voor en na. */
    verschil(ids){
      const nieuw = new Set(ids);
      const alle = APP.matches;
      const goals = alle.filter(m => nieuw.has(m.id)).reduce((s, m) => s + m.goals.length, 0);
      const alleenNieuw = sleutels => sleutels.filter(([, lijst]) => lijst.length && lijst.every(i => nieuw.has(i))).length;
      const per_ = f => { const o = {}; alle.forEach(m => f(m).forEach(k => (o[k] ||= []).push(m.id))); return Object.entries(o); };
      const spelers = Object.values(SPELERS).filter(p => p.m && p.m.length && p.m.every(r => nieuw.has(r[0]))).length;
      return {
        duels:   {nu: APP.totals.matches, bij: ids.length},
        goals:   {nu: APP.totals.goals, bij: goals},
        spelers: {nu: Object.keys(SPELERS).length, bij: spelers},
        grounds: {nu: APP.totals.venues, bij: alleenNieuw(per_(m => m.venue ? [m.venue] : []))},
        clubs:   {nu: APP.totals.clubs, bij: alleenNieuw(per_(m => [m.hid, m.aid]))},
      };
    },
    /* Alle duels met minstens één zin, nieuwste eerst. */
    logboek(){
      return APP.matches.map(m => ({m, zinnen: this.van(m.id).zinnen})).filter(x => x.zinnen.length);
    },
    /* De mijlpalen die het dichtst bij zijn, met hoe ver je al bent sinds de
       vorige. */
    volgende(aantal = 4){
      const uit = [];
      const voeg = (tekst, n, vorig, volgend, href) => {
        if (volgend == null) return;
        uit.push({tekst, nog: volgend - n, voortgang: (n - vorig) / (volgend - vorig), href});
      };
      voeg(`Je ${volgendeDuel(S.duels)}e duel`, S.duels, vorigeDuel(S.duels), volgendeDuel(S.duels), 'duels.html');
      const g = S.goals, gv = Math.floor(g / 100) * 100;
      voeg(`Goal nr. ${getal(gv + 100)}`, g, gv, gv + 100, 'duels.html');
      // Alleen wie je in je laatste tien duels nog zag: een speler die al
      // jaren weg is, haalt zijn volgende mijlpaal niet meer.
      const recent = new Set(M.slice(-10).flatMap(m => (perDuel[m.id] || []).map(s => s.id)));
      const beste = (teller, lijst, n, filter = () => true) => Object.entries(teller)
        .map(([id, x]) => ({id, x, vlg: volgendeUit(lijst, x), vrg: vorigeUit(lijst, x)}))
        .filter(r => r.vlg && filter(r.id)).sort((p, q) => (q.x - q.vrg) / (q.vlg - q.vrg) - (p.x - p.vrg) / (p.vlg - p.vrg)).slice(0, n);
      for (const r of beste(S.gezien, DREMPEL.speler, 2, id => recent.has(id)))
        voeg(`${esc(SPELERS[r.id].n)}, ${r.vlg} keer gezien`, r.x, r.vrg, r.vlg, H.speler(r.id));
      for (const r of beste(S.goalsSp, DREMPEL.spelerGoals, 1, id => recent.has(id)))
        voeg(`${esc(SPELERS[r.id].n)}, ${r.vlg} goals`, r.x, r.vrg, r.vlg, H.speler(r.id));
      for (const r of beste(S.ground, DREMPEL.ground, 1))
        voeg(`${r.vlg}e bezoek aan ${esc((venues[r.id] || {}).name || r.id)}`, r.x, r.vrg, r.vlg, H.stadion(r.id));
      for (const r of beste(S.club, DREMPEL.club, 1))
        voeg(`${esc(naamClub(+r.id))}, ${r.vlg} keer`, r.x, r.vrg, r.vlg, H.club(r.id));
      // Je volgende duel-mijlpaal staat er altijd bij; de rest op hoe dichtbij.
      const [duel, ...rest] = uit;
      return [duel, ...rest.sort((p, q) => q.voortgang - p.voortgang).slice(0, aantal - 1)];
    },
  };
}

/* ── Weergave ────────────────────────────────────────────────────────── */
const ICO = {
  bal:'<circle cx="10" cy="10" r="7.5"/><path d="M10 6.4 13.4 8.9 12.1 12.9H7.9L6.6 8.9z"/>',
  stadion:'<ellipse cx="10" cy="8" rx="7.5" ry="3"/><path d="M2.5 8v4.5c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V8"/><ellipse cx="10" cy="8" rx="3.4" ry="1.1"/>',
  schild:'<path d="M10 2.5 16 4.8v4.8c0 3.9-2.7 6.6-6 7.9-3.3-1.3-6-4-6-7.9V4.8z"/>',
  vlag:'<path d="M5 17.5V3"/><path d="M5 3.5h9.5l-2 3.25 2 3.25H5"/>',
  ster:'<path d="M10 2.8l2.2 4.6 5 .6-3.7 3.4 1 5-4.5-2.5-4.5 2.5 1-5L2.8 8l5-.6z"/>',
  kroon:'<path d="M3 6.5l3.8 3.2L10 4l3.2 5.7L17 6.5l-1.6 8.5H4.6z"/>',
  persoon:'<circle cx="10" cy="6.8" r="3.2"/><path d="M3.8 17c.6-3.3 3.1-5.2 6.2-5.2s5.6 1.9 6.2 5.2"/>',
  reeks:'<path d="M3 14.5l4-4 3 3 6.5-6.5"/><path d="M12.5 7h4v4"/>',
  album:'<rect x="3.5" y="3.5" width="5.5" height="5.5" rx="1.2"/><rect x="11" y="3.5" width="5.5" height="5.5" rx="1.2"/><rect x="3.5" y="11" width="5.5" height="5.5" rx="1.2"/><rect x="11" y="11" width="5.5" height="5.5" rx="1.2" stroke-dasharray="2 1.6"/>',
  kaart:'<rect x="6.5" y="3" width="7.5" height="12.5" rx="1.4" transform="rotate(12 10 10)"/>',
  publiek:'<circle cx="6" cy="7.5" r="2.3"/><circle cx="14" cy="7.5" r="2.3"/><path d="M2 15.5c.4-2.4 2-3.8 4-3.8s3.6 1.4 4 3.8M10 15.5c.4-2.4 2-3.8 4-3.8s3.6 1.4 4 3.8"/>',
  klok:'<circle cx="10" cy="10" r="7.5"/><path d="M10 5.5V10l3 2"/>',
  keer:'<path d="M4 6.5h7.5a4 4 0 0 1 0 8H5"/><path d="M7.5 11.5 4.5 14.5l3 3"/>',
  wereld:'<circle cx="10" cy="10" r="7.5"/><path d="M2.5 10h15M10 2.5c2.2 2.1 3.2 4.6 3.2 7.5s-1 5.4-3.2 7.5c-2.2-2.1-3.2-4.6-3.2-7.5S7.8 4.6 10 2.5z"/>',
  beker:'<path d="M6 3.5h8v4a4 4 0 0 1-8 0z"/><path d="M6 5H3.8a2.4 2.4 0 0 0 2.6 3.5M14 5h2.2a2.4 2.4 0 0 1-2.6 3.5M10 11.5v3M7 16.5h6"/>',
  kalender:'<rect x="3" y="4.5" width="14" height="12" rx="2"/><path d="M3 8.5h14M7 2.5v4M13 2.5v4"/>',
  goal:'<path d="M2.5 15.5V5.5h15v10"/><path d="M2.5 9h15M7.5 5.5v10M12.5 5.5v10" opacity=".45"/>',
  nul:'<circle cx="10" cy="10" r="6.5"/>',
};

/* Eén nieuwtje als rij: icoon, zin, tweede regel, eventueel een meter.
   Met een href is de rij aan te tikken. */
function rij(x, {metDuel = null} = {}){
  const ico = `<span class="nw-ico${x.gewicht === 'groot' ? ' groot' : ''}${x.ico === 'kaart' ? ' rood' : ''}" aria-hidden="true">`
    + `<svg viewBox="0 0 20 20">${ICO[x.ico] || ICO.ster}</svg></span>`;
  const sub = [x.sub, metDuel].filter(Boolean).join(' · ');
  const meter = x.meter ? `<span class="nw-meter"><span class="meter" aria-hidden="true">`
    + `<i style="width:${Math.round(x.meter[0] / x.meter[1] * 100)}%"></i></span>`
    + `<span class="nw-s">${x.meterTekst || ''}</span></span>` : '';
  const binnen = `${ico}<span class="nw-main"><span class="nw-t">${x.tekst}</span>`
    + `${sub ? `<span class="nw-s">${sub}</span>` : ''}${meter}</span>`;
  return x.href
    ? `<a class="nw" href="${x.href}">${binnen}<span class="chev" aria-hidden="true">›</span></a>`
    : `<div class="nw">${binnen}</div>`;
}
const feitjes = lijst => lijst.length
  ? `<div class="feitjes">${lijst.map(x => `<span class="feitje">${x.tekst}</span>`).join('')}</div>` : '';

const api = {bereken, rij, feitjes, THUIS, DREMPEL, ICO, km};
root.Nieuwtjes = api;
if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
