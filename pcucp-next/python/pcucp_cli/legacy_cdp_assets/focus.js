// Legacy ProseMirror focus, with mandatory editor/focus verification before input.
function(args) {
  var el = document.querySelector(args.selector);
  if (!el) return null;
  if (!el.isContentEditable || el.disabled || el.getAttribute('aria-disabled') === 'true')
    return {ok: false};
  el.focus();
  el.scrollIntoView();
  return {ok: document.activeElement === el, value: el.innerText || el.textContent || ''};
}
