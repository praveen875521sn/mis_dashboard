// Tab switching
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
  document.getElementById(tabId).classList.add('active');
}

// Achievement badge helper
function badgeClass(pct) {
  if (pct === 0) return 'zero';
  if (pct >= 90) return 'green';
  if (pct >= 60) return 'amber';
  return 'red';
}

// FY selector change → reload page
document.addEventListener('DOMContentLoaded', function() {
  const fySelect = document.getElementById('fy-select');
  if (fySelect) {
    fySelect.addEventListener('change', function() {
      const url = new URL(window.location.href);
      url.searchParams.set('fy', this.value);
      window.location.href = url.toString();
    });
  }

  // Highlight current month column
  const now = new Date();
  const currentMonth = now.getMonth() + 1;
  document.querySelectorAll(`[data-month="${currentMonth}"]`).forEach(el => {
    el.classList.add('today-month');
  });
});
