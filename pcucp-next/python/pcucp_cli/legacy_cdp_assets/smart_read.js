// Fixed legacy read algorithm; throwOnSideEffect is mandatory. No mutation branch.
function(args){
  const action = args.action;
  const needleRaw = args.needle;
  const textToType = args.text || '';
  const clearFirst = args.clear;
  const pressEnter = args.enter;
  const planOnly = true;
  function norm(s) {
    try { s = (s || '').toString().normalize('NFKC'); } catch(e) { s = (s || '').toString(); }
    return s.toLowerCase().replace(/[^\p{L}\p{N}\s]+/gu, ' ').replace(/\s+/g, ' ').trim();
  }
  function visible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (!r || r.width < 1 || r.height < 1) return false;
    const cs = window.getComputedStyle(el);
    if (!cs || cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity || 1) === 0) return false;
    return true;
  }
  function inputType(el) {
    return ((el && el.getAttribute && el.getAttribute('type')) || 'text').toLowerCase();
  }
  function typeable(el) {
    const tag = (el && el.tagName || '').toLowerCase();
    if (!el) return false;
    if (el.isContentEditable || tag === 'textarea') return true;
    if (tag !== 'input') return false;
    return !/^(button|submit|reset|checkbox|radio|file|image|range|color|hidden)$/i.test(inputType(el));
  }
  function setNativeValue(el, value) {
    const tag = (el.tagName || '').toLowerCase();
    const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const own = Object.getOwnPropertyDescriptor(el, 'value');
    const base = Object.getOwnPropertyDescriptor(proto, 'value');
    if (base && base.set && (!own || own.set !== base.set)) base.set.call(el, value);
    else el.value = value;
  }
  function fireValueEvents(el, data) {
    try { el.dispatchEvent(new InputEvent('input', { bubbles: true, data: data || null, inputType: 'insertText' })); }
    catch(e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function textParts(el) {
    const parts = [];
    const attrs = ['aria-label','title','placeholder','alt','name','id','value'];
    for (const a of attrs) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) parts.push(v);
    }
    if (el.labels) {
      for (const l of Array.from(el.labels)) {
        if (l && l.innerText) parts.push(l.innerText);
      }
    }
    if (el.tagName === 'LABEL' && el.control) {
      parts.push(el.innerText || '');
      const c = el.control;
      for (const a of ['aria-label','title','placeholder','name','id']) {
        const v = c.getAttribute && c.getAttribute(a);
        if (v) parts.push(v);
      }
    } else {
      parts.push(el.innerText || el.textContent || '');
    }
    return parts.map(p => (p || '').toString()).filter(Boolean);
  }
  function scoreText(parts, needle) {
    let best = 0;
    let bestText = '';
    for (const raw of parts) {
      const hay = norm(raw);
      if (!hay) continue;
      let score = 0;
      if (hay === needle) score = 100;
      else if (hay.startsWith(needle)) score = 88;
      else if (hay.includes(needle)) {
        const ratio = Math.min(1, needle.length / Math.max(1, hay.length));
        score = 62 + Math.floor(ratio * 25);
      } else if (needle.length >= 2 && hay.includes(needle.slice(0, Math.min(3, needle.length)))) {
        score = 25;
      }
      if (score > best) { best = score; bestText = raw; }
    }
    return { score: best, text: bestText };
  }
  function roleWeight(el, action) {
    const tag = (el.tagName || '').toLowerCase();
    const role = (el.getAttribute && (el.getAttribute('role') || '')) || '';
    const type = (el.getAttribute && (el.getAttribute('type') || '')) || '';
    if (action === 'type') {
      if (typeable(el) || role === 'textbox' || role === 'searchbox' || role === 'combobox') return 40;
      if (tag === 'label' && el.control) return 25;
      return -30;
    }
    if (tag === 'button' || tag === 'a' || role === 'button' || role === 'link' || role === 'menuitem' || role === 'tab') return 35;
    if (tag === 'input' && /button|submit|reset|checkbox|radio/.test(type)) return 35;
    if (el.onclick || tag === 'label' || tag === 'summary') return 20;
    return 0;
  }
  function attrQuote(v) {
    return (v || '').toString().replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, ' ');
  }
  function cssIdent(v) {
    try { if (window.CSS && CSS.escape) return CSS.escape(v); } catch(e) {}
    return (v || '').toString().replace(/[^a-zA-Z0-9_-]/g, function(ch) { return '\\' + ch; });
  }
  function selectorCandidates(el, matchedText, action) {
    const out = [];
    function push(kind, selector, score, reason) {
      if (!selector) return;
      if (out.some(x => x.selector === selector)) return;
      out.push({ kind, selector, score, reason });
    }
    const tag = (el.tagName || '').toLowerCase();
    const role = el.getAttribute && el.getAttribute('role');
    const id = el.getAttribute && el.getAttribute('id');
    if (id) push('css_id', '#' + cssIdent(id), 98, 'stable_id');
    for (const a of ['data-testid','data-test','data-cy','data-qa']) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) push('css_data_attr', '[' + a + '="' + attrQuote(v) + '"]', 96, a);
    }
    const aria = el.getAttribute && el.getAttribute('aria-label');
    if (aria) push('css_aria_label', '[aria-label="' + attrQuote(aria) + '"]', 90, 'aria_label');
    const name = el.getAttribute && el.getAttribute('name');
    if (name && tag) push('css_name', tag + '[name="' + attrQuote(name) + '"]', 84, 'name_attr');
    const placeholder = el.getAttribute && el.getAttribute('placeholder');
    if (placeholder) push('css_placeholder', '[placeholder="' + attrQuote(placeholder) + '"]', 82, 'placeholder');
    if (role) push('css_role', '[role="' + attrQuote(role) + '"]', 62, 'role_attr');
    if (tag) push('css_tag_fallback', tag, 35, 'last_resort_tag');
    out.sort((a,b) => b.score - a.score);
    return out.slice(0, 8);
  }
  function locatorCandidates(el, matchedText, action) {
    const out = [];
    function push(kind, locator, score, reason) {
      if (!locator) return;
      if (out.some(x => x.locator === locator)) return;
      out.push({ kind, locator, score, reason });
    }
    const nameJson = JSON.stringify(matchedText || needleRaw);
    const tag = (el.tagName || '').toLowerCase();
    const role = (el.getAttribute && (el.getAttribute('role') || '')) || '';
    const aria = el.getAttribute && el.getAttribute('aria-label');
    const placeholder = el.getAttribute && el.getAttribute('placeholder');
    if (action === 'type') {
      if (aria) push('playwright_label', 'page.getByLabel(' + JSON.stringify(aria) + ')', 100, 'aria_label');
      if (placeholder) push('playwright_placeholder', 'page.getByPlaceholder(' + JSON.stringify(placeholder) + ')', 94, 'placeholder');
      if (role === 'textbox' || role === 'searchbox') push('playwright_role', "page.getByRole('" + role + "', { name: " + nameJson + ' })', 86, 'role_textbox');
    } else {
      if (role === 'button' || tag === 'button') push('playwright_role', "page.getByRole('button', { name: " + nameJson + ' })', 100, 'button_name');
      if (role === 'link' || tag === 'a') push('playwright_role', "page.getByRole('link', { name: " + nameJson + ' })', 92, 'link_name');
      if (role === 'tab') push('playwright_role', "page.getByRole('tab', { name: " + nameJson + ' })', 90, 'tab_name');
      push('playwright_text', 'page.getByText(' + nameJson + ')', 70, 'visible_text');
    }
    out.sort((a,b) => b.score - a.score);
    return out.slice(0, 8);
  }
  function candidateSummary(c) {
    return {
      score: c.score,
      match_score: c.matchScore,
      matched_text: c.matchedText,
      tag_name: c.tag,
      role: c.role,
      rect: c.rect,
      selector_candidates: c.selectorCandidates,
      locator_candidates: c.locatorCandidates
    };
  }
  const needle = norm(needleRaw);
  if (!needle) return { ok: false, reason: 'empty_needle' };
  const selector = action === 'type'
    ? 'input,textarea,[contenteditable=true],[role=textbox],[role=searchbox],[role=combobox],label'
    : 'button,a,input,textarea,select,[role],[onclick],label,summary,[contenteditable=true]';
  // v1.4.0 DOM bridge v2: deep traversal — Shadow DOM + same-origin iframe
  // 기존 querySelectorAll 은 light-DOM 1뎁스만 보지만, Slack/Discord/Notion 같은
  // chromium 앱은 web component (shadowRoot) 와 same-origin iframe 안에 입력란이
  // 들어있는 경우가 많음. 보안상 cross-origin iframe 은 자동 스킵.
  function deepCollect(root, sel, out, hops) {
    if (!root || hops <= 0) return;
    try {
      const found = root.querySelectorAll ? root.querySelectorAll(sel) : [];
      for (let i = 0; i < found.length && out.length < 1200; i++) out.push(found[i]);
    } catch (e) { /* ignore selector errors */ }
    // shadow roots
    try {
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (let i = 0; i < all.length && out.length < 1200; i++) {
        const sr = all[i].shadowRoot;
        if (sr) deepCollect(sr, sel, out, hops - 1);
      }
    } catch (e) { /* ignore */ }
    // same-origin iframes
    try {
      const frames = root.querySelectorAll ? root.querySelectorAll('iframe,frame') : [];
      for (let i = 0; i < frames.length && out.length < 1200; i++) {
        let doc = null;
        try { doc = frames[i].contentDocument; } catch (e) { doc = null; }
        if (doc) deepCollect(doc, sel, out, hops - 1);
      }
    } catch (e) { /* ignore */ }
  }
  const nodes = [];
  deepCollect(document, selector, nodes, 4);
  // 동일 element 중복 제거 (shadow host + light child 같은 경우)
  const seen = new Set();
  const uniqueNodes = [];
  for (const n of nodes) {
    if (seen.has(n)) continue;
    seen.add(n);
    uniqueNodes.push(n);
    if (uniqueNodes.length >= 800) break;
  }
  const candidates = [];
  for (const el0 of uniqueNodes) {
    let el = el0;
    if (action === 'type' && el0.tagName === 'LABEL' && el0.control) el = el0.control;
    if (!visible(el0) && !visible(el)) continue;
    const parts = textParts(el0);
    if (el !== el0) parts.push(...textParts(el));
    const st = scoreText(parts, needle);
    if (st.score <= 0) continue;
    const r = (visible(el) ? el : el0).getBoundingClientRect();
    const area = Math.max(1, r.width * r.height);
    let score = st.score + roleWeight(el, action);
    if (area < 40000) score += 12;
    if (area > 180000) score -= 30;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') score -= 80;
    candidates.push({
      el,
      el0,
      score,
      matchScore: st.score,
      matchedText: st.text,
      tag: el.tagName,
      role: el.getAttribute('role') || '',
      rect: {x:r.x,y:r.y,width:r.width,height:r.height},
      selectorCandidates: selectorCandidates(el, st.text, action),
      locatorCandidates: locatorCandidates(el, st.text, action)
    });
  }
  candidates.sort((a,b) => b.score - a.score || a.rect.width*a.rect.height - b.rect.width*b.rect.height);
  const best = candidates[0];
  if (!best || best.score < 55) {
    return {
      ok: false,
      reason: 'no_text_match',
      candidate_count: candidates.length,
      top_score: best ? best.score : 0,
      candidate_summaries: candidates.slice(0, 5).map(candidateSummary)
    };
  }
  const el = best.el;

  return {
    ok: true,
    action,
    query: needleRaw,
    matched_text: best.matchedText,
    score: best.score,
    match_score: best.matchScore,
    tag_name: el.tagName,
    role: el.getAttribute('role') || '',
    rect: best.rect,
    selector_candidates: best.selectorCandidates,
    locator_candidates: best.locatorCandidates,
    candidate_summaries: candidates.slice(0, 5).map(candidateSummary),
    candidate_count: candidates.length,
    text_length: textToType.length,
    sent_enter: !planOnly && !!pressEnter,
    plan_only: !!planOnly
  };
}
