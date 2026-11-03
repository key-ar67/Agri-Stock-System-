(() => {
  const html = document.documentElement;
  const saved = localStorage.getItem('agristock-theme') || 'light';
  html.dataset.theme = saved;
  const themeBtn = document.getElementById('themeToggle');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    html.dataset.theme = html.dataset.theme === 'light' ? 'dark' : 'light';
    localStorage.setItem('agristock-theme', html.dataset.theme);
  });
  const menu = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  if (menu && sidebar) menu.addEventListener('click', () => sidebar.classList.toggle('open'));
  document.querySelectorAll('[data-table-search]').forEach(input => {
    input.addEventListener('input', () => {
      const table = input.closest('.panel').querySelector('tbody');
      const term = input.value.toLowerCase();
      table.querySelectorAll('tr').forEach(row => row.style.display = row.innerText.toLowerCase().includes(term) ? '' : 'none');
    });
  });
  // Subtle reveal motion inspired by common UI patterns: staggered entrance and lift-on-hover.
  const cards = document.querySelectorAll('.stat-card,.panel,.knowledge-card');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('revealed'); observer.unobserve(entry.target); }
    }), { threshold: .08 });
    cards.forEach(card => { card.classList.add('will-reveal'); observer.observe(card); });
  }
})();