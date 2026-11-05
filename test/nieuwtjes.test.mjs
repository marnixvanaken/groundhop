// Toets voor app/nieuwtjes.js: wat elk duel jou opleverde.
//
// Werkt op een kleine, verzonnen verzameling, zodat elke uitkomst vaststaat
// en de toets niet breekt als er een echt duel bij komt. Staat
// app/app-data.js er (python3 app/build_app_data.py), dan draait hij
// daarna ook één keer over je echte data, om te zien dat niets struikelt.
//
//     node --test test/nieuwtjes.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';

const require = createRequire(import.meta.url);
const N = require('../app/nieuwtjes.js');
const tekst = x => x.tekst.replace(/<[^>]+>/g, '');

/* Een verzameling uit een lijst duels, oudste eerst. Een duel:
   {datum, thuis, uit, stand: [h, a], ground, goals: [[min, speler, ploeg]],
    spelers: [[speler, ploeg, minuten]]} */
const CLUBS = {1: 'Thuisclub', 2: 'Bezoekers', 3: 'Derden'};
const GROUNDS = {
  Dorp: {key: 'Dorp', name: 'Dorpsveld', city: 'Grubbenvorst', country: 'Nederland', lat: 51.42, lon: 6.14},
  Stad: {key: 'Stad', name: 'Stadsstadion', city: 'Eindhoven', country: 'Nederland', lat: 51.44, lon: 5.47},
  Ver:  {key: 'Ver', name: 'Verre Arena', city: 'Lissabon', country: 'Portugal', lat: 38.75, lon: -9.18},
};
const SPELERS_BASIS = {
  p1: {n: 'Piet Een', c: 'nl'}, p2: {n: 'Jan Twee', c: 'nl'}, p3: {n: 'Kofi Drie', c: 'gh'},
  p4: {n: 'Luis Vier', c: 'ec'}, p5: {n: 'Bank Vijf', c: 'ga'},
};
function maak(duels){
  const SPELERS = {};
  for (const [id, p] of Object.entries(SPELERS_BASIS)) SPELERS[id] = {...p, m: []};
  const matches = duels.map((d, i) => {
    const id = 1000 + i;
    for (const [pid, team, min] of d.spelers || []){
      const g = (d.goals || []).filter(x => x[1] === pid).length;
      SPELERS[pid].m.push([id, team, min, g, 0, min > 0 ? 1 : 0, null]);
    }
    const thuis = CLUBS[d.thuis], uit = CLUBS[d.uit];
    return {
      id, date: d.datum, season: +d.datum.slice(0, 4) - (+d.datum.slice(5, 7) < 7 ? 1 : 0),
      hid: d.thuis, aid: d.uit, hs: d.stand[0], as: d.stand[1], t: d.comp || 'Competitie',
      venue: d.ground || 'Stad', att: d.publiek || null, nat: 0, elf: [], cards: [], pen: null,
      goals: (d.goals || []).map(([min, pid, team]) => ({min, add: null, p: SPELERS[pid].n, pid, team: team === 'h' ? thuis : uit, type: 'regular'})),
    };
  });
  for (const id of Object.keys(SPELERS)) if (!SPELERS[id].m.length) delete SPELERS[id];
  const venues = Object.values(GROUNDS).map(v => ({...v, visits: 0, first: null}));
  for (const m of matches){
    const v = venues.find(x => x.key === m.venue);
    v.visits++; v.first ||= m.date;
  }
  const APP = {
    matches: matches.slice().reverse(),
    clubs: Object.entries(CLUBS).map(([id, name]) => ({id: +id, name})),
    venues: venues.filter(v => v.visits), albums: [],
    totals: {matches: matches.length, goals: matches.reduce((s, m) => s + m.goals.length, 0),
             venues: venues.filter(v => v.visits).length, clubs: 3},
  };
  return {APP, SPELERS, ids: matches.map(m => m.id)};
}
const soorten = (R, id) => { const v = R.van(id); return [...v.zinnen, ...v.feitjes].map(x => x.soort); };
const vind = (R, id, soort) => [...R.van(id).zinnen, ...R.van(id).feitjes].find(x => x.soort === soort);

test('je eerste duel en een nieuwe ground met afstand vanaf Grubbenvorst', () => {
  const {APP, SPELERS, ids} = maak([
    {datum: '2020-08-01', thuis: 1, uit: 2, stand: [1, 0], ground: 'Stad', spelers: [['p1', 'Thuisclub', 90]]},
    {datum: '2020-08-08', thuis: 1, uit: 2, stand: [0, 0], ground: 'Ver', spelers: [['p1', 'Thuisclub', 90]]},
  ]);
  const R = N.bereken(APP, SPELERS);
  assert.equal(tekst(vind(R, ids[0], 'duel-mijlpaal')), 'Je eerste duel');
  const ground = vind(R, ids[1], 'nieuwe-ground');
  assert.match(tekst(ground), /Nieuwe ground: Verre Arena/);
  assert.match(ground.sub, /ground nr\. 2 · \d\.\d{3} km van Grubbenvorst/);
  assert.match(tekst(vind(R, ids[1], 'nieuw-land-ground')), /Je eerste duel in Portugal/);
  assert.ok(vind(R, ids[1], 'verste-ground'));
  assert.ok(!vind(R, ids[0], 'nieuw-land-ground'), 'je eerste land is geen nieuwtje');
});

test('een reeks ongeslagen eindigt', () => {
  const duels = [];
  for (let i = 0; i < 8; i++) duels.push({datum: `2021-09-${String(i + 1).padStart(2, '0')}`, thuis: 1, uit: 2, stand: [1, 1]});
  duels.push({datum: '2021-09-20', thuis: 1, uit: 2, stand: [0, 2]});
  const {APP, SPELERS, ids} = maak(duels);
  const R = N.bereken(APP, SPELERS);
  const z = R.van(ids[8]).zinnen.find(x => x.soort === 'reeks-voorbij' && x.tekst.includes('Thuisclub'));
  assert.equal(tekst(z), 'Thuisclub verloor voor het eerst in 9 duels met jou erbij');
  assert.equal(z.sub, 'Nooit eerder verloren met jou erbij');
});

test('een nieuw land telt alleen wie echt speelde', () => {
  const {APP, SPELERS, ids} = maak([
    {datum: '2022-08-01', thuis: 1, uit: 2, stand: [0, 0], spelers: [['p1', 'Thuisclub', 90]]},
    {datum: '2022-08-08', thuis: 1, uit: 2, stand: [0, 0],
     spelers: [['p3', 'Bezoekers', 70], ['p5', 'Bezoekers', 0]]},
  ]);
  const R = N.bereken(APP, SPELERS);
  const land = R.van(ids[1]).zinnen.filter(x => x.soort === 'nieuw-land-speler');
  assert.equal(land.length, 1);
  assert.match(tekst(land[0]), /Voor het eerst een speler uit .+: Kofi Drie/);
  assert.match(land[0].sub, /Bezoekers · land nr\. 2/);
});

test('een nieuwe topscorer moet erover, gelijk komen is niet genoeg', () => {
  const {APP, SPELERS, ids} = maak([
    {datum: '2023-08-01', thuis: 1, uit: 2, stand: [2, 0], goals: [[10, 'p1', 'h'], [20, 'p1', 'h']],
     spelers: [['p1', 'Thuisclub', 90], ['p2', 'Thuisclub', 90]]},
    {datum: '2023-08-08', thuis: 1, uit: 2, stand: [2, 0], goals: [[10, 'p2', 'h'], [20, 'p2', 'h']],
     spelers: [['p1', 'Thuisclub', 90], ['p2', 'Thuisclub', 90]]},
    {datum: '2023-08-15', thuis: 1, uit: 2, stand: [1, 0], goals: [[30, 'p2', 'h']],
     spelers: [['p1', 'Thuisclub', 90], ['p2', 'Thuisclub', 90]]},
  ]);
  const R = N.bereken(APP, SPELERS);
  assert.ok(!soorten(R, ids[1]).includes('nieuwe-topscorer'), '2 tegen 2 is gelijk');
  const z = vind(R, ids[2], 'nieuwe-topscorer');
  assert.equal(tekst(z), 'Nieuwe nummer 1 van je topscorers: Jan Twee, 3 goals');
  assert.equal(z.sub, 'Neemt het over van Piet Een');
});

test('eindelijk een goal, na vijftien duels op het veld', () => {
  const duels = [];
  for (let i = 0; i < 15; i++) duels.push({datum: `2024-0${1 + Math.floor(i / 9)}-${String(1 + i % 9).padStart(2, '0')}`,
    thuis: 1, uit: 2, stand: i === 14 ? [1, 0] : [0, 0], goals: i === 14 ? [[50, 'p4', 'h']] : [],
    spelers: [['p4', 'Thuisclub', 80]]});
  const {APP, SPELERS, ids} = maak(duels);
  const R = N.bereken(APP, SPELERS);
  assert.equal(tekst(vind(R, ids[14], 'eindelijk-goal')), 'Na 15 duels eindelijk een goal van Luis Vier');
});

test('een oud duel toevoegen rekent alles opnieuw uit', () => {
  const later = {datum: '2025-03-01', thuis: 1, uit: 2, stand: [0, 0], spelers: [['p1', 'Thuisclub', 90], ['p4', 'Bezoekers', 90]]};
  const eerst = maak([{datum: '2025-01-01', thuis: 1, uit: 2, stand: [0, 0], spelers: [['p1', 'Thuisclub', 90]]}, later]);
  let R = N.bereken(eerst.APP, eerst.SPELERS);
  assert.ok(soorten(R, eerst.ids[1]).includes('nieuw-land-speler'));
  // Nu blijkt Luis Vier al in 2024 gezien, in een duel dat er later bij komt.
  const met = maak([
    {datum: '2024-06-01', thuis: 3, uit: 2, stand: [0, 0], spelers: [['p1', 'Derden', 90], ['p3', 'Bezoekers', 90], ['p4', 'Bezoekers', 90]]},
    {datum: '2025-01-01', thuis: 1, uit: 2, stand: [0, 0], spelers: [['p1', 'Thuisclub', 90]]}, later]);
  R = N.bereken(met.APP, met.SPELERS);
  assert.ok(!soorten(R, met.ids[2]).includes('nieuw-land-speler'), 'het land is nu al eerder gezien');
  assert.equal(tekst(vind(R, met.ids[0], 'duel-mijlpaal')), 'Je eerste duel');
  const v = R.verschil([met.ids[0]]);
  assert.deepEqual([v.duels.bij, v.clubs.bij, v.spelers.bij], [1, 1, 1]);
});

test('groot gaat voor gewoon, en klein is een feitje', () => {
  const {APP, SPELERS, ids} = maak([
    {datum: '2020-08-01', thuis: 1, uit: 2, stand: [0, 0], ground: 'Dorp', publiek: 500},
    {datum: '2020-08-08', thuis: 1, uit: 3, stand: [0, 0], ground: 'Ver', publiek: 900},
  ]);
  const R = N.bereken(APP, SPELERS);
  const {zinnen, feitjes} = R.van(ids[1]);
  const orde = {groot: 0, gewoon: 1};
  zinnen.forEach((x, i) => i && assert.ok(orde[zinnen[i - 1].gewicht] <= orde[x.gewicht]));
  assert.ok(feitjes.every(x => x.gewicht === 'klein'));
  assert.ok(feitjes.some(x => x.soort === 'publiek'));
});

const DATA = new URL('../app/app-data.js', import.meta.url);
test('je echte data', {skip: !existsSync(DATA) && 'bouw eerst app/app-data.js'}, () => {
  globalThis.window = globalThis;
  require('../app/app-data.js');
  require('../app/speler-data.js');
  const R = N.bereken(globalThis.APP, globalThis.SPELERS);
  for (const m of globalThis.APP.matches){
    for (const x of [...R.van(m.id).zinnen, ...R.van(m.id).feitjes]){
      assert.ok(x.tekst && !/undefined|NaN|\[object/.test(x.tekst + x.sub), `${m.date}: ${x.tekst} ${x.sub}`);
    }
  }
  const mijlpalen = globalThis.APP.matches.flatMap(m => R.van(m.id).zinnen.filter(x => x.soort === 'goal-mijlpaal'));
  assert.equal(mijlpalen.length, Math.floor(globalThis.APP.matches.reduce((s, m) => s + m.goals.length, 0) / 100));
  assert.ok(R.volgende().length >= 1);
});
