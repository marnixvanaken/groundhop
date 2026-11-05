/* GroundHop — overgangen tussen schermen.

   Staat in de <head> van elk scherm, vóór de rest: de richting moet op
   <html> staan voordat het nieuwe scherm voor het eerst getekend wordt.

   Bij een tik op een link bepaalt dit script de richting en bewaart die voor
   het volgende scherm:
   - dieper: van een lijst naar een detail, schuift van rechts naar binnen;
   - terug:  de terugknop, schuift naar rechts weg;
   - tab:    een andere tab, vervaagt op zijn plek.
   De animaties zelf staan in groundhop.css (@view-transition).

   Tik je op een duel, dan krijgen de twee logo's en de uitslag in die rij een
   naam; op de wedstrijd dragen het scorebord en de uitslag dezelfde namen,
   zodat ze van de rij naar het scorebord vliegen. Terug gaat andersom.

   Een browser zonder View Transitions slaat dit allemaal over. */
(function(){
  const SLEUTEL = 'gh-vt';
  const TABS = ['index.html', 'duels.html', 'grounds.html', 'spelers.html', 'meer.html'];
  const NAMEN = ['vt-thuis', 'vt-uit', 'vt-uitslag'];
  const bestand = u => new URL(u, location.href).pathname.split('/').pop() || 'index.html';
  const wedstrijdId = u => new URLSearchParams(new URL(u, location.href).hash.slice(1)).get('id');

  function wisNamen(){
    document.querySelectorAll('.vt-gedeeld').forEach(el => {
      el.style.viewTransitionName = '';
      el.classList.remove('vt-gedeeld');
    });
  }
  // Geef de logo's en de uitslag van een duel-link hun namen.
  function benoem(a){
    const crests = a.querySelectorAll(
      '.duel-crests > *, .laatste-crests > .crest, .laatste-crests > .crest-fallback');
    const uitslag = a.querySelector('.duel-score, .laatste-uitslag');
    if (crests.length < 2 || !uitslag) return;
    [crests[0], crests[1], uitslag].forEach((el, i) => {
      el.style.viewTransitionName = NAMEN[i];
      el.classList.add('vt-gedeeld');
    });
  }

  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
    const a = e.target.closest('a[href]');
    if (!a || a.target) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    const van = bestand(location.href), naar = bestand(url.href);
    if (van === naar && url.pathname === location.pathname && url.hash !== location.hash
        && naar !== 'wedstrijddetail.html') return;   // zelfde scherm, andere hash
    let richting = 'dieper';
    if (a.hasAttribute('data-terug')) richting = 'terug';
    else if (a.closest('.tabbar') || (TABS.includes(naar) && TABS.includes(van))) richting = 'tab';
    let id = null;
    // Terug van een wedstrijd: het scorebord houdt zijn namen en vliegt naar
    // de rij. Anders gaan alle namen eraf, en krijgt alleen een aangetikt
    // duel ze.
    if (richting === 'terug' && van === 'wedstrijddetail.html') id = wedstrijdId(location.href);
    else {
      wisNamen();
      if (richting === 'dieper' && naar === 'wedstrijddetail.html'){ benoem(a); id = wedstrijdId(url.href); }
    }
    try { sessionStorage.setItem(SLEUTEL, JSON.stringify({richting, id, t: Date.now()})); } catch {}
  }, true);

  // Het nieuwe scherm: richting op <html>, en bij terugkomen van een
  // wedstrijd de namen op de rij van dat duel.
  window.addEventListener('pagereveal', e => {
    let r = null;
    try { r = JSON.parse(sessionStorage.getItem(SLEUTEL) || 'null'); sessionStorage.removeItem(SLEUTEL); } catch {}
    const vers = r && Date.now() - r.t < 5000;
    if (!e.viewTransition) return;
    if (!vers){ delete document.documentElement.dataset.vt; return; }
    document.documentElement.dataset.vt = r.richting;
    if (r.richting === 'terug' && r.id){
      wisNamen();
      const a = document.querySelector(`a[href$="wedstrijddetail.html#id=${r.id}"]`);
      if (a) benoem(a);
    }
    // Na terugkomen gaan de namen van de rij weer af, zodat een volgende tik
    // op een ander duel geen dubbele namen geeft.
    if (r.richting === 'terug') e.viewTransition.finished.finally(wisNamen);
  });
})();
