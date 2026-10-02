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
  // Public-text boundary: values are not labels, except visible input captions.
  // Read calls keep this fixed traversal under mandatory throwOnSideEffect.
  function sourceOnly(el) {
    return !!el && /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test((el.tagName || '').toUpperCase());
  }
  function textExcluded(el) {
    return sourceOnly(el) || !!el && (el.tagName || '').toUpperCase() === 'TEXTAREA';
  }
  function excludedBySource(el) {
    let node = el;
    for (let depth = 0; node && depth < 128; depth++, node = node.parentElement) {
      if (sourceOnly(node)) return true;
    }
    return !!node; // Excessive ancestry is excluded, never treated as public.
  }
  function publicText(el, rendered) {
    if (!el || excludedBySource(el) || textExcluded(el)) return '';
    if (!el.querySelector('script,style,noscript,template,textarea'))
      return (rendered ? el.innerText : el.textContent) || '';
    // Aggregate getters would include source-only or textarea value text. Rebuild only this
    // affected subtree; normal labels retain their original browser text exactly.
    const stack = [el], parts = [];
    let visited = 0;
    while (stack.length && visited < 1200) {
      const node = stack.pop(); visited++;
      if (typeof node === 'string') {
        if (!parts.length || !parts[parts.length - 1].endsWith('\n')) parts.push(node);
        continue;
      }
      if (textExcluded(node)) continue;
      if (node.nodeType === 3) { parts.push(node.nodeValue || ''); continue; }
      if (node.nodeType !== 1) continue;
      if (rendered) {
        const cs = window.getComputedStyle(node);
        if (!cs || cs.display === 'none' || /^(hidden|collapse)$/.test(cs.visibility)) continue;
        if (node.tagName === 'BR') { parts.push('\n'); continue; }
        if (node !== el && /^(block|flex|grid|list-item|table|table-row)$/.test(cs.display)) {
          if (!parts.length || !parts[parts.length - 1].endsWith('\n')) parts.push('\n');
          stack.push('\n');
        }
      }
      const children = node.childNodes;
      if (children.length + stack.length > 1200) return '';
      for (let i = children.length - 1; i >= 0; i--) stack.push(children[i]);
    }
    if (stack.length) return '';
    const text = parts.join('');
    return rendered ? text.replace(/^\n+|\n+$/g, '') : text;
  }
  function inputCaption(el) {
    if (!el || el.tagName !== 'INPUT' ||
        !/^(button|submit|reset)$/i.test(el.getAttribute('type') || '')) return '';
    const rect = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    if (!rect || rect.width < 1 || rect.height < 1 || !cs || cs.display === 'none' ||
        /^(hidden|collapse)$/.test(cs.visibility) || Number(cs.opacity || 1) === 0) return '';
    return el.value || ''; // Current rendered caption, never a stale value attribute.
  }
  function textParts(el){
    if (excludedBySource(el)) return [];
    var p=[];
    try{
      var rendered = publicText(el, true); if (rendered) p.push(rendered);
      var content = publicText(el, false); if (content) p.push(content);
      var caption = inputCaption(el); if (caption) p.push(caption);
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
      if (excludedBySource(el)) continue;
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
