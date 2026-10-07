/* Ripple ពេលចុចប៊ូតុង */
document.addEventListener('click', function (e) {
  var b = e.target.closest('.btn,.btn-soft,.btn-green,.btn-red,.btn-manage,.btn-social,.qa,.pw,.chip-btn');
  if (!b || b.disabled) return;
  var r = b.getBoundingClientRect(), s = Math.max(r.width, r.height);
  var el = document.createElement('span');
  el.className = 'ui-ripple';
  el.style.cssText = 'width:' + s + 'px;height:' + s + 'px;left:' + (e.clientX - r.left - s / 2) + 'px;top:' + (e.clientY - r.top - s / 2) + 'px';
  b.appendChild(el);
  setTimeout(function () { el.remove(); }, 600);
});

/* ពណ៌ progress bar តាមកម្រិតប្រើប្រាស់: <60% បៃតង · 60–85% លឿង · >85% ក្រហម */
(function () {
  function lvl(el) {
    var w = parseFloat(el.style.width);
    if (isNaN(w)) return;
    el.setAttribute('data-level', w >= 85 ? 'high' : w >= 60 ? 'mid' : 'low');
  }
  function scan(root) { (root || document).querySelectorAll('.bar>span,.track>span').forEach(lvl); }
  function start() {
    scan();
    new MutationObserver(function (ms) {
      ms.forEach(function (m) {
        if (m.type === 'attributes' && m.target.matches && m.target.matches('.bar>span,.track>span')) lvl(m.target);
        else if (m.type === 'childList') scan(m.target);
      });
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
