(() => {
  'use strict';

  const exportWithoutMediaBtn = document.getElementById('exportWithoutMediaBtn');
  const exportWithMediaBtn = document.getElementById('exportWithMediaBtn');
  const includeMaps = document.getElementById('backupIncludeMaps');
  const restoreForm = document.getElementById('restoreForm');
  const backupFile = document.getElementById('backupFile');
  const backupFileName = document.getElementById('backupFileName');
  const restoreBtn = document.getElementById('restoreBtn');
  const backupProgress = document.getElementById('backupProgress');
  const backupStatus = document.getElementById('backupStatus');
  const restoreConfirmDialog = document.getElementById('restoreConfirmDialog');
  const cancelRestoreBtn = document.getElementById('cancelRestoreBtn');
  const confirmRestoreBtn = document.getElementById('confirmRestoreBtn');
  let pending = false;

  function errorMessage(data, fallback) {
    const message = data?.error?.message;
    return typeof message === 'string' && message.trim() ? message : fallback;
  }

  function setPending(value, progressValue = null) {
    pending = value;
    exportWithoutMediaBtn.disabled = value;
    exportWithMediaBtn.disabled = value;
    restoreBtn.disabled = value;
    backupFile.disabled = value;
    confirmRestoreBtn.disabled = value;
    cancelRestoreBtn.disabled = value;
    backupProgress.classList.toggle('hidden', !value);
    backupProgress.removeAttribute('value');
    if (Number.isFinite(progressValue)) backupProgress.value = progressValue;
    restoreForm.setAttribute('aria-busy', String(value));
  }

  function downloadName(response) {
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const candidate = match?.[1]?.trim();
    return candidate && /^[A-Za-z0-9._-]+$/.test(candidate)
      ? candidate
      : 'offline360-studio-backup.zip';
  }

  async function exportBackup(includesMedia) {
    if (pending) return;
    setPending(true);
    backupStatus.textContent = includesMedia
      ? 'Backup mit Medien wird erstelltâ€¦'
      : 'Backup ohne Medien wird erstelltâ€¦';
    try {
      const response = await fetch('/api/backup/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          includes_media: includesMedia,
          includes_maps: includeMaps.checked
        })
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(errorMessage(data, `Export fehlgeschlagen (HTTP ${response.status}).`));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = downloadName(response);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      backupStatus.textContent = 'Backup wurde erfolgreich erstellt und heruntergeladen.';
    } catch (error) {
      backupStatus.textContent = `Export fehlgeschlagen: ${error.message || 'Unbekannter Fehler.'}`;
    } finally {
      setPending(false);
    }
  }

  function closeConfirmDialog() {
    if (restoreConfirmDialog.open) restoreConfirmDialog.close();
  }

  function restoreBackup() {
    const file = backupFile.files?.[0];
    if (!file || pending) return;
    closeConfirmDialog();
    setPending(true, 0);
    backupStatus.textContent = 'Backup wird hochgeladen und geprÃ¼ftâ€¦';

    const formData = new FormData();
    formData.append('file', file);
    const request = new XMLHttpRequest();
    request.open('POST', '/api/backup/import');
    request.responseType = 'json';
    request.upload.addEventListener('progress', event => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      backupProgress.value = percent;
      backupStatus.textContent = `Backup wird hochgeladenâ€¦ ${percent}%`;
    });
    request.addEventListener('load', () => {
      const data = request.response;
      if (request.status < 200 || request.status >= 300) {
        backupStatus.textContent = `Restore fehlgeschlagen: ${errorMessage(
          data,
          `Serverfehler (HTTP ${request.status}).`
        )}`;
      } else {
        const safetyName = typeof data?.safety_backup === 'string' ? data.safety_backup : '';
        backupStatus.textContent = safetyName
          ? `Restore erfolgreich. Sicherheitsbackup: ${safetyName}. Bitte Offline360 Studio neu starten.`
          : 'Restore erfolgreich. Bitte Offline360 Studio neu starten.';
        backupFile.value = '';
        backupFileName.textContent = 'Keine Datei ausgewÃ¤hlt.';
      }
      setPending(false);
    });
    request.addEventListener('error', () => {
      backupStatus.textContent = 'Restore fehlgeschlagen: Der Server ist nicht erreichbar.';
      setPending(false);
    });
    request.addEventListener('abort', () => {
      backupStatus.textContent = 'Restore wurde abgebrochen.';
      setPending(false);
    });
    request.send(formData);
  }

  exportWithoutMediaBtn.addEventListener('click', () => exportBackup(false));
  exportWithMediaBtn.addEventListener('click', () => exportBackup(true));
  backupFile.addEventListener('change', () => {
    const file = backupFile.files?.[0];
    backupFileName.textContent = file?.name || 'Keine Datei ausgewÃ¤hlt.';
  });
  restoreForm.addEventListener('submit', event => {
    event.preventDefault();
    if (!backupFile.files?.length || pending) {
      backupStatus.textContent = 'Bitte zuerst eine ZIP-Datei auswÃ¤hlen.';
      backupFile.focus();
      return;
    }
    if (typeof restoreConfirmDialog.showModal === 'function') {
      restoreConfirmDialog.showModal();
      cancelRestoreBtn.focus();
    } else {
      restoreConfirmDialog.setAttribute('open', '');
    }
  });
  cancelRestoreBtn.addEventListener('click', closeConfirmDialog);
  confirmRestoreBtn.addEventListener('click', restoreBackup);
  restoreConfirmDialog.addEventListener('cancel', event => {
    if (pending) event.preventDefault();
  });
})();

