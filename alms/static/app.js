(function () {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

  // Confirm dialogs for destructive actions
  document.addEventListener('submit', (e) => {
    const msg = e.target.getAttribute('data-confirm');
    if (msg && !confirm(msg)) e.preventDefault();
  });

  // Sidebar toggle on small screens
  document.getElementById('sidebarToggle')?.addEventListener('click', () => document.querySelector('.sidebar')?.classList.toggle('open'));

  // Render barcodes
  if (window.JsBarcode) {
    document.querySelectorAll('svg[data-barcode]').forEach((el) => {
      JsBarcode(el, el.dataset.barcode, { format: 'CODE128', height: +(el.dataset.height || 40), width: +(el.dataset.width || 1.6), fontSize: 13, margin: 4, displayValue: true });
    });
  }

  // Live OPAC search (FR-03)
  const live = document.getElementById('liveSearch');
  if (live) {
    const results = document.getElementById('searchResults');
    let timer;
    const run = () => {
      const params = new URLSearchParams(new FormData(live));
      history.replaceState(null, '', '?' + params.toString());
      params.set('partial', '1');
      const t0 = performance.now();
      fetch(live.action + '?' + params.toString()).then((r) => r.text()).then((html) => {
        results.innerHTML = html;
        const el = document.getElementById('searchTiming');
        if (el) el.textContent = `${Math.round(performance.now() - t0)} ms`;
      });
    };
    live.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 180); });
    live.addEventListener('change', run);
    live.addEventListener('submit', (e) => { e.preventDefault(); run(); });
  }

  // Circulation desk: member lookup panel + copy lookup
  const memberInput = document.getElementById('memberCode');
  const memberPanel = document.getElementById('memberPanel');
  if (memberInput && memberPanel) {
    let t;
    const load = () => {
      const code = memberInput.value.trim();
      if (!code) { memberPanel.innerHTML = '<div class="text-muted small p-3">Scan or type a member ID to load their profile, active loans and dues.</div>'; return; }
      fetch(memberPanel.dataset.url + '?code=' + encodeURIComponent(code)).then((r) => r.text()).then((h) => { memberPanel.innerHTML = h; });
    };
    memberInput.addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
    memberInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); load(); document.getElementById('issueBarcode')?.focus(); } });
    if (memberInput.value) load();
  }
  document.querySelectorAll('[data-copy-info]').forEach((input) => {
    const out = document.getElementById(input.dataset.copyInfo);
    let t;
    const load = () => {
      const code = input.value.trim();
      if (!code) { out.innerHTML = ''; return; }
      fetch(out.dataset.url + '?barcode=' + encodeURIComponent(code)).then((r) => r.json()).then((d) => {
        if (!d.found) { out.innerHTML = '<span class="text-danger"><i class="bi bi-x-circle"></i> Unknown barcode</span>'; return; }
        const colors = { available: 'success', loaned: 'primary', on_hold: 'warning', damaged: 'danger', lost: 'dark', discarded: 'secondary' };
        let extra = '';
        if (d.loan) extra = ` · on loan to <b>${d.loan.name}</b> (${d.loan.member_code}), due ${d.loan.due_date}`;
        if (d.hold) extra = ` · reserved for <b>${d.hold.name}</b> (${d.hold.member_code}) until ${d.hold.expires_at}`;
        out.innerHTML = `<i class="bi bi-book"></i> <b>${d.title}</b> — ${d.author} <span class="badge text-bg-${colors[d.status] || 'secondary'}">${d.status.replace('_', ' ')}</span>${extra}`;
      });
    };
    input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
    if (input.value) load();
  });

  // Demo login quick-fill
  document.querySelectorAll('[data-demo-user]').forEach((btn) => btn.addEventListener('click', () => {
    document.getElementById('username').value = btn.dataset.demoUser;
    document.getElementById('password').value = btn.dataset.demoPass;
    document.getElementById('loginForm').submit();
  }));

  // Select-all checkbox helper
  document.querySelectorAll('[data-check-all]').forEach((box) => box.addEventListener('change', () => {
    document.querySelectorAll(box.dataset.checkAll).forEach((c) => { c.checked = box.checked; c.dispatchEvent(new Event('change')); });
  }));
  // Live total for fine selections
  const totalEl = document.getElementById('selectedTotal');
  if (totalEl) {
    const upd = () => {
      let s = 0; document.querySelectorAll('input[name="fine_id"]:checked').forEach((c) => { s += parseFloat(c.dataset.amount); });
      totalEl.textContent = '₹' + s.toLocaleString('en-IN');
    };
    document.querySelectorAll('input[name="fine_id"]').forEach((c) => c.addEventListener('change', upd)); upd();
  }
  window.ALMS = { csrf };
})();
