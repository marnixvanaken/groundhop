// Past elk scherm op een telefoon?
//
// Loopt de hele app door op telefoonbreedtes (320, 375, 390 en 430 pixels)
// en tikt op elke schakelaar en elk chipje, ook die pas na een tik
// verschijnen. Per stand meldt hij vier soorten fouten:
//
//   scroll   een scrollgebied (de pagina, de pop-up) schuift opzij; alleen
//            een chiprij mag dat
//   buiten   een element steekt buiten het scherm
//   geknipt  een element valt buiten de kaart waarin het staat
//   tekst    tekst die niet afbreekt en buiten beeld of buiten zijn kaart
//            loopt; een bewuste ellips (…) telt niet
//
// Zo kwam Nieuwtjes eraan: de chiprij stond direct op de pagina, 100% breed
// plus een eigen marge, en de hele pagina schoof 16 pixels opzij.
//
// Hij start zelf een webserver op de repo en heeft alleen app/app-data.js
// nodig (python3 app/build_app_data.py). Plaatjes en lettertypes laadt hij
// niet: die veranderen niets aan de breedte.
//
//     npm i playwright && npx playwright install chromium
//     node test/breedte.test.mjs             een greep: elk scherm, 15 duels, 8 stadions, …
//     node test/breedte.test.mjs --alles     elk duel, stadion, club en album
//     node test/breedte.test.mjs --zelftest  ziet hij een fout die er expres in staat?
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const MAP = fileURLToPath(new URL('..', import.meta.url));
const ALLES = process.argv.includes('--alles');
const ZELFTEST = process.argv.includes('--zelftest');
const BREEDTES = [320, 375, 390, 430];

if (!existsSync(join(MAP, 'app/app-data.js')) || !existsSync(join(MAP, 'app/speler-data.js'))){
  console.log('  ! app/app-data.js ontbreekt; draai eerst python3 app/build_app_data.py');
  process.exit(1);
}
globalThis.window = {};
require(join(MAP, 'app/app-data.js'));
require(join(MAP, 'app/speler-data.js'));
const APP = globalThis.window.APP, SPELERS = globalThis.window.SPELERS;

// ── Een kale webserver op de repo ───────────────────────────────────────────
const SOORT = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
               '.png': 'image/png', '.json': 'application/json', '.webmanifest': 'application/manifest+json'};
const server = createServer(async (req, res) => {
  const pad = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^([/\\])+/, '');
  try {
    const inhoud = await readFile(join(MAP, pad));
    res.writeHead(200, {'Content-Type': SOORT[extname(pad)] || 'application/octet-stream'});
    res.end(inhoud);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(klaar => server.listen(0, '127.0.0.1', klaar));
const BASIS = `http://127.0.0.1:${server.address().port}/app/`;

// ── Welke schermen ──────────────────────────────────────────────────────────
function schermen(){
  const greep = (lijst, n) => ALLES ? lijst : lijst.slice(0, n);
  const vaakst = Object.entries(SPELERS).sort((a, b) => b[1].seen - a[1].seen);
  const langst = Object.entries(SPELERS).sort((a, b) => (b[1].n || '').length - (a[1].n || '').length);
  // Een paar duels met lange clubnamen: die staan het eerst in de knel.
  const naam = id => (APP.clubs.find(c => c.id === id) || {}).name || '';
  const langeDuels = [...APP.matches].sort((a, b) =>
    (naam(b.hid) + naam(b.aid)).length - (naam(a.hid) + naam(a.aid)).length).slice(0, 5);
  return [
    'index.html', 'index.html#nieuw', 'duels.html', 'grounds.html', 'spelers.html', 'meer.html',
    'nieuwtjes.html', 'collecties.html', 'toevoegen.html',
    ...new Set([...greep(APP.matches, 15), ...langeDuels].map(m => `wedstrijddetail.html#id=${m.id}`)),
    ...greep(APP.venues, 8).map(v => `stadiondetail.html#v=${encodeURIComponent(v.key)}`),
    ...greep(APP.clubs, 8).map(c => `club.html#id=${c.id}`),
    ...APP.comps.map(c => `competitie.html#t=${encodeURIComponent(c.name)}`),
    ...(APP.albums || []).map(a => `album.html#id=${encodeURIComponent(a.id)}`),
    ...[...greep(vaakst, 6).slice(0, ALLES ? 40 : 6), ...langst.slice(0, ALLES ? 15 : 4)]
      .map(([id]) => `speler.html#id=${id}`),
  ];
}

// ── De controle, in de pagina ───────────────────────────────────────────────
function controleer(){
  const vw = document.documentElement.clientWidth;
  const main = document.querySelector('main');
  const uit = [];
  const naam = el => {
    const deel = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
      + (e.classList.length ? '.' + [...e.classList].join('.') : '');
    return (el.parentElement ? deel(el.parentElement) + ' > ' : '') + deel(el);
  };
  const tekst = el => (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50);
  const stijl = el => getComputedStyle(el);
  const knipt = el => stijl(el).overflowX !== 'visible';
  const schuift = el => ['auto', 'scroll'].includes(stijl(el).overflowX);

  // Elk scrollgebied scrollt alleen omlaag; alleen een chiprij schuift opzij.
  for (const el of document.querySelectorAll('body, body *')){
    if (!schuift(el) || el.classList.contains('chips')) continue;
    if (el.scrollWidth > el.clientWidth + 1)
      uit.push({soort: 'scroll', wat: `${naam(el)} schuift ${el.scrollWidth - el.clientWidth}px opzij`});
  }

  for (const el of document.querySelectorAll('body *')){
    if (['SCRIPT', 'STYLE', 'TEMPLATE'].includes(el.tagName) || el.closest('svg')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = stijl(el);
    if (s.visibility === 'hidden' || +s.opacity === 0 || el.closest('[hidden]')) continue;
    // In een chiprij mag het opzij buiten beeld staan; dat is het schuiven.
    if (el.parentElement?.closest('.chips')) continue;
    // De kaart (of ander vak) die afknipt wat eruit steekt.
    let kader = null;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement)
      if (p !== main && knipt(p) && !schuift(p)){ kader = p; break; }
    // Wat er zichtbaar van over is na alle knippende voorouders.
    let L = r.left, R = r.right;
    for (let q = el.parentElement; q && q !== document.body; q = q.parentElement)
      if (q !== main && knipt(q) && !schuift(q)){ const k = q.getBoundingClientRect(); L = Math.max(L, k.left); R = Math.min(R, k.right); }

    // Tekst meten, niet het vak: het vak kan keurig binnen blijven terwijl de
    // tekst erbuiten loopt.
    const stukken = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
    if (stukken.length && s.textOverflow !== 'ellipsis'){
      const rg = document.createRange();
      let tl = Infinity, tr = -Infinity;
      for (const n of stukken){
        rg.selectNodeContents(n);
        const q = rg.getBoundingClientRect();
        if (q.width){ tl = Math.min(tl, q.left); tr = Math.max(tr, q.right); }
      }
      let gl = 0, gr = vw, waar = 'scherm';
      if (kader){ const k = kader.getBoundingClientRect(); gl = Math.max(0, k.left); gr = Math.min(vw, k.right); waar = naam(kader); }
      const over = Math.max(tr - gr, gl - tl);
      if (tr > tl && over > 1) uit.push({soort: 'tekst', wat: naam(el), tekst: tekst(el), px: Math.round(over), in: waar});
    }

    if (R > vw + 1 || L < -1)
      uit.push({soort: 'buiten', wat: naam(el), tekst: tekst(el), px: Math.round(Math.max(R - vw, -L))});
    else if (kader){
      const k = kader.getBoundingClientRect();
      const over = Math.max(r.right - k.right, k.left - r.left);
      if (over > 2 && s.textOverflow !== 'ellipsis')
        uit.push({soort: 'geknipt', wat: naam(el), tekst: tekst(el), px: Math.round(over), in: naam(kader)});
    }
  }
  return uit;
}

// ── Doorlopen ───────────────────────────────────────────────────────────────
const browser = await chromium.launch(process.env.CHROMIUM ? {executablePath: process.env.CHROMIUM} : {});
async function context(breedte){
  const ctx = await browser.newContext({viewport: {width: breedte, height: 800}, reducedMotion: 'reduce'});
  // Plaatjes en lettertypes van buiten: niet nodig, en vaak niet bereikbaar.
  await ctx.route(/^https?:\/\/(?!127\.0\.0\.1)/, r => r.abort());
  await ctx.route(/\/img\//, r => r.abort());
  // Net gebruikt, zodat de intro op Home niet over alles heen ligt.
  await ctx.addInitScript(() => { try { localStorage.setItem('gh-laatst', String(Date.now())); } catch {} });
  return ctx;
}
async function open(p, pad){
  await p.goto('about:blank');
  await p.goto(BASIS + pad, {waitUntil: 'load'});
  await p.waitForTimeout(150);
}

if (ZELFTEST){
  // Elke soort fout één keer expres erin; de controle moet hem vinden, en op
  // een schoon scherm niets.
  const ctx = await context(390), p = await ctx.newPage();
  let mis = 0;
  const proef = async (wat, pad, verwacht, js) => {
    await open(p, pad);
    if (js) await p.evaluate(js);
    const soorten = [...new Set((await p.evaluate(controleer)).map(x => x.soort))];
    const ok = verwacht ? soorten.includes(verwacht) : !soorten.length;
    console.log(`  ${ok ? '✓' : '✗'} ${wat}${ok ? '' : `  (kreeg: ${soorten.join(', ') || 'niets'})`}`);
    mis += ok ? 0 : 1;
  };
  await proef('Duels zonder fout', 'duels.html', null);
  await proef('een te breed blok op de pagina', 'duels.html', 'scroll',
    () => { const d = document.createElement('div'); d.style.cssText = 'width:600px;height:20px;flex:none'; document.querySelector('main').append(d); });
  await proef('een chiprij met eigen marge op de pagina', 'meer.html', 'scroll',
    () => { const d = document.createElement('div'); d.className = 'chips'; d.style.cssText = 'margin:12px 16px;flex:none;width:100%'; d.innerHTML = '<button>a</button>'; document.querySelector('main').prepend(d); });
  await proef('een te lange titel in de bovenbalk', 'meer.html', 'buiten',
    () => { const h = document.querySelector('.bar h1'); h.style.whiteSpace = 'nowrap'; h.textContent = 'Een hele lange titel die nooit op één regel past, ook niet op een brede telefoon'; });
  await proef('tekst die niet afbreekt in een kaart', 'meer.html', 'tekst',
    () => { const d = document.createElement('div'); d.style.whiteSpace = 'nowrap'; d.textContent = 'x'.repeat(200); document.querySelector('.card').append(d); });
  await proef('een blok dat uit zijn kaart steekt', 'meer.html', 'geknipt',
    () => { const d = document.createElement('div'); d.style.cssText = 'width:120%;height:10px;background:red'; document.querySelector('.card').append(d); });
  await browser.close(); server.close();
  console.log(mis ? `\n  ${mis} niet gezien` : '\n  alles gezien');
  process.exit(mis ? 1 : 0);
}

const lijst = schermen();
const gevonden = new Map();   // soort|wat|in → {…, waar: Set, breedtes: Set, px}
const paginafouten = [];
for (const breedte of BREEDTES){
  const ctx = await context(breedte), p = await ctx.newPage();
  p.on('pageerror', e => paginafouten.push(`${breedte}px ${p.url().split('/app/')[1]}: ${e.message}`));
  const noteer = (bevindingen, waar) => bevindingen.forEach(x => {
    const k = `${x.soort}|${x.wat}|${x.in || ''}`;
    if (!gevonden.has(k)) gevonden.set(k, {...x, waar: new Set(), breedtes: new Set(), px: 0});
    const g = gevonden.get(k);
    g.waar.add(waar); g.breedtes.add(breedte); g.px = Math.max(g.px, x.px || 0);
  });
  for (const pad of lijst){
    await open(p, pad);
    noteer(await p.evaluate(controleer), pad);
    // Elke schakelaar en elk chipje één keer, ook wat pas na een tik verschijnt.
    const gehad = new Set();
    for (let n = 0; n < 150; n++){
      const knoppen = await p.$$eval('main button[aria-pressed]', bs => bs.map(b => {
        const d = Object.entries(b.dataset);
        return d.length ? 'main button' + d.map(([k, v]) =>
          `[data-${k.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}="${CSS.escape(v)}"]`).join('') : null;
      }).filter(Boolean));
      const volgende = knoppen.find(k => !gehad.has(k));
      if (!volgende) break;
      gehad.add(volgende);
      try { await p.click(volgende, {timeout: 1500}); } catch { continue; }
      await p.waitForTimeout(60);
      noteer(await p.evaluate(controleer), `${pad} › ${volgende.replace('main button', '')}`);
    }
  }
  await ctx.close();
}
await browser.close(); server.close();

console.log(`  ${lijst.length} schermen op ${BREEDTES.join(', ')} pixels`);
for (const g of gevonden.values()){
  const waar = [...g.waar];
  console.log(`\n  ✗ [${g.soort}] ${g.wat}${g.in ? `  (in ${g.in})` : ''}${g.px ? `, ${g.px}px` : ''}`
    + `  op ${[...g.breedtes].join('/')} px`);
  if (g.tekst) console.log(`      “${g.tekst}”`);
  console.log(`      ${waar.length}×: ${waar.slice(0, 3).join(' | ')}${waar.length > 3 ? ' …' : ''}`);
}
paginafouten.slice(0, 10).forEach(f => console.log(`  ! ${f}`));
const fout = gevonden.size + paginafouten.length;
console.log(fout ? `\n  ${gevonden.size} plekken te breed, ${paginafouten.length} paginafouten` : '  ✓ alles past');
process.exit(fout ? 1 : 0);
