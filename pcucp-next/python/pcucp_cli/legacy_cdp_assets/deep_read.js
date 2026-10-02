// Fixed legacy read algorithm; throwOnSideEffect is mandatory.
function(args){
  var report = { hops:4, shadow_roots_seen:0, iframes_seen:0, iframes_blocked:0, total_nodes:0 };
  var matches = [];
  function norm(s){ return (s||'').toString().toLowerCase().replace(/\s+/g,' ').trim(); }
  function scoreText(parts, needle){
    var best=0, bestText=null;
    for (var i=0;i<parts.length;i++){
      var t = norm(parts[i]);
      if (!t) continue;
      if (t === needle) { if (best<100){best=100;bestText=parts[i];} }
      else if (t.indexOf(needle) >= 0) { if (best<70){best=70;bestText=parts[i];} }
    }
    return { score:best, text:bestText };
  }
  function textParts(el){
    var p=[];
    try{
      if (el.innerText) p.push(el.innerText);
      if (el.textContent) p.push(el.textContent);
      if (el.value) p.push(el.value);
      if (el.placeholder) p.push(el.placeholder);
      if (el.title) p.push(el.title);
      var aria = el.getAttribute && el.getAttribute('aria-label');
      if (aria) p.push(aria);
      var n = el.getAttribute && el.getAttribute('name');
      if (n) p.push(n);
      var id = el.id; if (id) p.push(id);
    } catch(e){}
    return p;
  }
  function deep(root, hops){
    if (!root || hops <= 0) return;
    var all=[];
    try { all = root.querySelectorAll ? root.querySelectorAll('*') : []; } catch(e){}
    report.total_nodes += all.length;
    for (var i=0;i<all.length && matches.length<25;i++){
      var el = all[i];
      var parts = textParts(el);
      var st = scoreText(parts, NEEDLE);
      if (st.score > 0){
        var r=null;
        try{ r = el.getBoundingClientRect(); } catch(e){}
        matches.push({
          tag: el.tagName ? el.tagName.toLowerCase() : null,
          score: st.score,
          matched_text: st.text ? st.text.substring(0,80) : null,
          rect: r ? {x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)} : null
        });
      }
      if (el.shadowRoot) {
        report.shadow_roots_seen++;
        deep(el.shadowRoot, hops-1);
      }
      if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
        report.iframes_seen++;
        var doc=null;
        try { doc = el.contentDocument; } catch(e){ doc=null; }
        if (doc) deep(doc, hops-1);
        else report.iframes_blocked++;
      }
    }
  }
  var NEEDLE = norm(args.needle);
  deep(document, report.hops);
  matches.sort(function(a,b){return b.score-a.score;});
  return { traversal: report, found_count: matches.length, top_matches: matches.slice(0,8) };
}
