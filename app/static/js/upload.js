// VIC OCR — drag-and-drop upload + job submit
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var dropzone = document.getElementById('dropzone');
    var fileInput = document.getElementById('file-input');
    var fileName = document.getElementById('file-name');
    var form = document.getElementById('upload-form');
    var submitBtn = document.getElementById('upload-submit');
    var engineCards = document.querySelectorAll('.engine-card');
    var engineInput = document.getElementById('engine-input');
    var progressWrap = document.getElementById('upload-progress');
    var progressBar = progressWrap ? progressWrap.querySelector('.progress-bar') : null;

    if (!dropzone || !fileInput) return;

    dropzone.addEventListener('click', function () { fileInput.click(); });

    ['dragenter', 'dragover'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) {
        e.preventDefault();
        dropzone.classList.add('is-dragover');
      });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
      dropzone.addEventListener(evt, function (e) {
        e.preventDefault();
        dropzone.classList.remove('is-dragover');
      });
    });
    dropzone.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        updateFileName();
      }
    });
    fileInput.addEventListener('change', updateFileName);

    function updateFileName() {
      if (fileInput.files && fileInput.files[0]) {
        fileName.textContent = fileInput.files[0].name + ' (' + VIC.formatBytes(fileInput.files[0].size) + ')';
      } else {
        fileName.textContent = '';
      }
    }

    engineCards.forEach(function (card) {
      card.addEventListener('click', function () {
        if (card.classList.contains('is-disabled')) {
          VIC.showToast('Engine này chưa được cấu hình. Hãy vào Cài đặt.', 'warning');
          return;
        }
        engineCards.forEach(function (c) { c.classList.remove('is-selected'); });
        card.classList.add('is-selected');
        engineInput.value = card.getAttribute('data-engine');
      });
    });

    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!fileInput.files || !fileInput.files[0]) {
          VIC.showToast('Vui lòng chọn file PDF', 'warning');
          return;
        }
        if (!engineInput.value) {
          VIC.showToast('Vui lòng chọn OCR engine', 'warning');
          return;
        }

        var fd = new FormData();
        fd.append('file', fileInput.files[0]);
        fd.append('engine', engineInput.value);
        fd.append('csrf_token', VIC.csrfToken());

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Đang tải lên...';
        if (progressWrap) progressWrap.classList.remove('d-none');

        var xhr = new XMLHttpRequest();
        xhr.open('POST', form.getAttribute('action'), true);
        xhr.setRequestHeader('X-CSRFToken', VIC.csrfToken());
        xhr.upload.onprogress = function (ev) {
          if (ev.lengthComputable && progressBar) {
            var pct = (ev.loaded / ev.total) * 100;
            progressBar.style.width = pct + '%';
            progressBar.textContent = pct.toFixed(0) + '%';
          }
        };
        xhr.onload = function () {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<i class="bi bi-rocket-takeoff me-1"></i>Bắt đầu OCR';
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              var resp = JSON.parse(xhr.responseText);
              if (resp.success && resp.data && resp.data.id) {
                VIC.showToast('Đã tạo job #' + resp.data.id, 'success');
                window.location.href = '/jobs/' + resp.data.id;
                return;
              }
            } catch (e) { /* fall through */ }
            VIC.showToast('Tải lên hoàn tất nhưng phản hồi không hợp lệ', 'warning');
          } else {
            try {
              var err = JSON.parse(xhr.responseText);
              VIC.showToast(err.error && err.error.message || 'Tải lên thất bại', 'error');
            } catch (e) {
              VIC.showToast('Tải lên thất bại (HTTP ' + xhr.status + ')', 'error');
            }
          }
        };
        xhr.onerror = function () {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<i class="bi bi-rocket-takeoff me-1"></i>Bắt đầu OCR';
          VIC.showToast('Lỗi mạng khi tải lên', 'error');
        };
        xhr.send(fd);
      });
    }
  });
})();
