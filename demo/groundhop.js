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
