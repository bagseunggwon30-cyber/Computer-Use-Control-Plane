// Legacy DOM action; invoked only after immutable startup live authorization.
function(args){
  var el = document.querySelector(args.selector);
  if (!el) return { ok: false, reason: 'selector_not_found' };
  try { el.focus(); } catch(e) {}
  var isCE = el.isContentEditable;
  var isInput = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
  if (args.clear) {
    if (isCE) { el.textContent = ''; }
    else if (isInput) { el.value = ''; }
  }
  var newText = args.text;
  if (newText) {
    if (isCE) { el.textContent += newText; }
    else if (isInput) { el.value += newText; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  var sentEnter = false;
  if (args.enter) {
    var ev = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true });
    el.dispatchEvent(ev);
    var ev2 = new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true });
    el.dispatchEvent(ev2);
    var ev3 = new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true });
    el.dispatchEvent(ev3);
    sentEnter = true;
  }
  var current = isCE ? el.textContent : (isInput ? el.value : '');
  return {
    ok: true,
    selector: args.selector,
    tag_name: el.tagName,
    is_content_editable: isCE,
    is_input: isInput,
    current_value_length: (current||'').length,
    sent_enter: sentEnter
  };
}
