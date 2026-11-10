'use strict';
(() => {
  const sidebar = document.getElementById('sidebar');
  const scrim = document.querySelector('.sidebar-scrim');
  const toggles = [...document.querySelectorAll('[data-menu-toggle]')];
  const mobile = window.matchMedia('(max-width:850px)');
  let lastMenuFocus;
  function setMenu(open) {
    if (!sidebar) return;
    if (open) lastMenuFocus = document.activeElement;
    sidebar.classList.toggle('is-open', open);
    document.body.classList.toggle('menu-open', open && mobile.matches);
    if (scrim) scrim.hidden = !open;
    sidebar.inert = mobile.matches && !open;
    toggles.forEach(button => button.setAttribute('aria-expanded', String(open)));
    if (open) sidebar.querySelector('a')?.focus();
    else if (lastMenuFocus && mobile.matches) lastMenuFocus.focus();
  }
  toggles.forEach(button => button.addEventListener('click', () => setMenu(!sidebar?.classList.contains('is-open'))));
  scrim?.addEventListener('click', () => setMenu(false));
  mobile.addEventListener('change', () => setMenu(false));
  if (sidebar) sidebar.inert = mobile.matches;
  document.addEventListener('keydown', event => {
    if (!sidebar?.classList.contains('is-open')) return;
    if (event.key === 'Escape') setMenu(false);
    if (event.key === 'Tab' && mobile.matches) {
      const links = [...sidebar.querySelectorAll('a,button')];
      const first = links[0], last = links.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  const dialog = document.getElementById('confirmModal');
  let pendingForm;
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('.js-delete-form')) return;
    event.preventDefault();
    pendingForm = form;
    document.getElementById('confirmText').textContent = form.dataset.msg || 'Deseja excluir este registro?';
    dialog.showModal();
    document.getElementById('btnCancel').focus();
  });
  document.getElementById('btnCancel')?.addEventListener('click', () => { pendingForm = null; dialog.close(); });
  document.getElementById('btnConfirm')?.addEventListener('click', () => {
    const form = pendingForm;
    pendingForm = null;
    dialog.close();
    if (form) HTMLFormElement.prototype.submit.call(form);
  });
  dialog?.addEventListener('cancel', () => { pendingForm = null; });
  dialog?.addEventListener('click', event => {
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  document.querySelectorAll('table:not(.responsive-table)').forEach(table => {
    if (table.closest('.table-wrap,.overflow-x-auto')) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'table-wrap';
    table.before(wrapper);
    wrapper.append(table);
  });
  if (location.hash === '#novo') document.querySelector('.create-details')?.setAttribute('open', '');
})();
