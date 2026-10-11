function openSettings() { document.getElementById('settings-panel').classList.add('open'); }
function closeSettings() { document.getElementById('settings-panel').classList.remove('open'); }

function setPage(n) {
  document.getElementById('page').value = n;
  htmx.trigger('#filters', 'change');
}

// Changing a filter (not the page itself) goes back to the newest page.
['change', 'input'].forEach((type) => document.addEventListener(type, (e) => {
  const form = e.target.closest && e.target.closest('#filters');
  if (form && e.target !== form && e.target.id !== 'page') document.getElementById('page').value = 1;
}, true));
