// VIC OCR — common front-end helpers
(function () {
  'use strict';

  function showToast(message, variant) {
    variant = variant || 'info';
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container position-fixed top-0 end-0 p-3';
      container.style.zIndex = 1080;
      document.body.appendChild(container);
    }
    var iconMap = {
      success: 'bi-check-circle-fill text-success',
      error: 'bi-x-circle-fill text-danger',
      warning: 'bi-exclamation-triangle-fill text-warning',
      info: 'bi-info-circle-fill text-info'
    };
    var iconCls = iconMap[variant] || iconMap.info;
    var el = document.createElement('div');
    el.className = 'toast align-items-center';
    el.setAttribute('role', 'alert');
    el.innerHTML = ''
      + '<div class="toast-header">'
      + '  <i class="bi ' + iconCls + ' me-2"></i>'
      + '  <strong class="me-auto">VIC OCR</strong>'
      + '  <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>'
      + '</div>'
      + '<div class="toast-body">' + message + '</div>';
    container.appendChild(el);
    var t = new bootstrap.Toast(el, { delay: 4500 });
    t.show();
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return bytes.toFixed(1) + ' ' + units[i];
  }

  window.VIC = {
    showToast: showToast,
    csrfToken: csrfToken,
    formatBytes: formatBytes
  };
})();
