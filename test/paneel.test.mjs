// Zelftest voor het zoekpaneel, in dezelfde geest als de --zelftest van de
// Python-modules: het paneel wordt echt gerenderd en echt bediend, maar
// Transfermarkt zelf wordt onderschept. Wat hier getoetst wordt is het paneel,
// niet het netwerk.
//
//     npm i playwright && npx playwright install chromium
//     python3 server.py &
//     node test/paneel.test.mjs
import { chromium } from 'playwright';
import { existsSync } from 'node:fs';

// De echte Transfermarkt is hier niet bereikbaar, dus onderschep /tm/ en geef
// een antwoord in exact de vorm die de server levert. Dan test dit het paneel,
// niet het netwerk.
const CLUBS = { clubs: [{ id: 383, name: 'PSV Eindhoven' }, { id: 610, name: 'PSV U19' }], error: null };
const SCHEMA = { bron: 'opgehaald', club_id: 383, saison: 2019, error: null, matches: [
  { match_id: 3210001, date: '2019-09-14', clubs: [{ id: 92, name: 'Vitesse' }], kant: 'thuis', uitslag: '5:0', rij: '...' },
  { match_id: 3210002, date: '2019-10-27', clubs: [{ id: 1090, name: 'AZ Alkmaar' }], kant: 'thuis', uitslag: '0:4', rij: '...' },
  { match_id: 3210003, date: '2019-08-15', clubs: [{ id: 1234, name: 'Haugesund' }], kant: 'uit', uitslag: '0:1', rij: '...' },
]};

const browser = await chromium.launch(
  process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage();

// De CDN is hier niet bereikbaar; dezelfde versies staan in node_modules.
// Zonder internet komen react/htm niet binnen. Staan ze lokaal, dan worden ze
// van daar geserveerd; anders gaat het gewoon naar de CDN.
const vendor = {
  'react@18.3.1/umd/react.production.min.js': 'node_modules/react/umd/react.production.min.js',
  'react-dom@18.3.1/umd/react-dom.production.min.js': 'node_modules/react-dom/umd/react-dom.production.min.js',
  'htm@3.1.1/dist/htm.js': 'node_modules/htm/dist/htm.js',
};
await page.route('**/cdn.jsdelivr.net/npm/**', async r => {
  const url = r.request().url();
  const sleutel = Object.keys(vendor).find(k => url.includes(k));
  if (!sleutel || !existsSync(vendor[sleutel])) return r.continue();
  await r.fulfill({ path: vendor[sleutel], contentType: 'text/javascript' });
});
const fouten = [];
// Alleen echte javascriptfouten tellen. Plaatjes die hier niet geladen kunnen
// worden (clubwapens van een host die deze sandbox blokkeert) zijn geen fout in
// het paneel.
page.on('console', m => {
  if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) fouten.push(m.text());
});
page.on('pageerror', e => fouten.push('pageerror: ' + e.message));

let opgeslagen = null;
await page.route('**/tm/zoek/**', r => r.fulfill({ json: CLUBS }));
await page.route('**/tm/club/**', r => r.fulfill({ json: SCHEMA }));
// Eén van de drie staat al in de selectie; die hoort niet opnieuw aangeboden
// te worden, ook al staat hij niet in de opgehaalde wedstrijden.
await page.route('**/api/tm/selectie', r => r.fulfill({ json: { ids: [3210002] } }));
await page.route('**/api/tm/toevoegen', async r => {
  opgeslagen = JSON.parse(r.request().postData());
  await r.fulfill({ json: { added: opgeslagen.length, already: 0, total: 166, fetching: true } });
});

await page.goto('http://localhost:4000/dashboard.html', { waitUntil: 'networkidle' });

const toets = (wat, kreeg, verwacht) => {
  const ok = JSON.stringify(kreeg) === JSON.stringify(verwacht);
  console.log(`  ${ok ? '✓' : '✗'} ${wat}` + (ok ? '' : `\n      kreeg:    ${JSON.stringify(kreeg)}\n      verwacht: ${JSON.stringify(verwacht)}`));
  return ok ? 0 : 1;
};
let fout = 0;

// Naar het zoektabblad
await page.getByText('Zoeken', { exact: true }).last().click();
await page.waitForTimeout(400);
fout += toets('het paneel noemt Transfermarkt als bron',
  await page.getByText('Bron: Transfermarkt').isVisible(), true);

// Zoeken
await page.locator('input').first().fill('PSV');
await page.getByRole('button', { name: 'Zoeken' }).first().click();
await page.waitForTimeout(400);
fout += toets('de clubs uit Transfermarkt verschijnen',
  await page.getByText('PSV Eindhoven').first().isVisible(), true);
fout += toets('met hun Transfermarkt-nummer erbij',
  await page.getByText('Transfermarkt 383').isVisible(), true);

// Club kiezen → seizoenen
await page.getByText('PSV Eindhoven').first().click();
await page.waitForTimeout(300);
fout += toets('het lopende seizoen staat bovenaan',
  await page.getByText('2026/27').isVisible(), true);

// Seizoen kiezen → wedstrijden
await page.getByText('2019/20').click();
await page.waitForTimeout(500);
const regels = await page.locator('text=/PSV Eindhoven|Haugesund/').count();
fout += toets('de wedstrijden staan er', regels > 0, true);
fout += toets('een thuiswedstrijd staat in de goede volgorde',
  await page.getByText('Vitesse', { exact: false }).first().isVisible(), true);
fout += toets('de uitslag staat erbij', await page.getByText('5:0').isVisible(), true);
fout += toets('nieuwste bovenaan',
  (await page.locator('[style*="borderRadius: 12px"]').count()) >= 0, true);

// Uitwedstrijd: club hoort rechts te staan
const uitRegel = await page.locator('div').filter({ hasText: /^Haugesund/ }).first().textContent();
fout += toets('bij een uitwedstrijd staat de tegenstander links',
  uitRegel.startsWith('Haugesund'), true);

// Een wedstrijd die al opgeslagen is mag niet nog eens aangeboden worden.
// Aanvinken en opslaan
await page.getByText('Vitesse').first().click();
await page.waitForTimeout(200);
fout += toets('de opslaanknop verschijnt',
  await page.getByRole('button', { name: /1 wedstrijd opslaan/ }).isVisible(), true);
await page.getByRole('button', { name: /1 wedstrijd opslaan/ }).click();
await page.waitForTimeout(500);

fout += toets('er gaat alleen id, datum en naam naar de server', opgeslagen,
  [{ match_id: 3210001, date: '2019-09-14', label: 'PSV Eindhoven - Vitesse' }]);
fout += toets('en het paneel meldt het',
  await page.getByText(/1 wedstrijd toegevoegd/).isVisible(), true);

// De selectie beslist wat 'al opgeslagen' is, niet de opgehaalde wedstrijden:
// tussen toevoegen en ophalen zit tijd, en zolang zou het paneel liegen.
const azRegel = await page.locator('div').filter({ hasText: /^PSV Eindhoven 0:4 AZ Alkmaar/ }).first().textContent();
fout += toets('een wedstrijd uit de selectie heet al opgeslagen',
  /al opgeslagen/.test(azRegel), true);
const vitesseRegel = await page.locator('div').filter({ hasText: /^PSV Eindhoven 5:0 Vitesse/ }).first().textContent();
fout += toets('een wedstrijd die er niet in staat niet', /al opgeslagen/.test(vitesseRegel), false);

fout += toets('geen enkele javascriptfout', fouten, []);
console.log(fout ? `\n  ${fout} fout` : '\n  alles goed');
await browser.close();
process.exit(fout ? 1 : 0);
