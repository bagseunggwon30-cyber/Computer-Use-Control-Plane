// Post-insertion verification; remains part of the explicitly authorized live action.
function(args) {
  var el = document.querySelector(args.selector);
  if (!el) return null;
  return el.innerText || el.textContent || '';
}
