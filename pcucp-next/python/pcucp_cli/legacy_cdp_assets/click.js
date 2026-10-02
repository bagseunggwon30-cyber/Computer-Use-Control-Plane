// Legacy DOM action; invoked only after immutable startup live authorization.
function(args){
  var el = document.querySelector(args.selector);
  if (!el) return { ok: false, reason: 'selector_not_found' };
  try { el.scrollIntoView({block:'center', behavior:'instant'}); } catch(e) {}
  try { el.focus(); } catch(e) {}
  el.click();
  return { ok: true, selector: args.selector, tag_name: el.tagName };
}
