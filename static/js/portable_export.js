(function () {
  'use strict';

  const form = document.getElementById('portableExportForm');
  if (!form) return;

  const projectSelect = document.getElementById('portableExportProject');
  const filenameInput = document.getElementById('portableExportFilename');
  const zipInput = document.getElementById('portableExportZip');
  const videosInput = document.getElementById('portableExportVideos');
  const mapInput = document.getElementById('portableExportMap');
  const tracksInput = document.getElementById('portableExportTracks');
  const exportButton = document.getElementById('portableExportBtn');
  const status = document.getElementById('portableExportStatus');
  const errorBox = document.getElementById('portableExportError');
  const adminProjectSelect = document.getElementById('adminProjectSelect');
  let pending = false;

  function showError(message = '') {
    errorBox.textContent = message;
    errorBox.classList.toggle('hidden', !message);
  }

  function safeSuggestedName(name) {
    return String(name || 'portable-tour')
      .normalize('NFKD')
      .replace(/[^\w.-]+/g, '-')
      .replace(/^[-_.]+|[-_.]+$/g, '')
      .toLowerCase() || 'portable-tour';
  }

  function setPending(value) {
    pending = value;
    exportButton.disabled = value;
    form.querySelectorAll('input, select').forEach(control => {
      control.disabled = value;
    });
  }

  function responseMessage(payload, fallback) {
    return payload?.error?.message || fallback;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function loadProjects() {
    try {
      const response = await fetch('/api/projects');
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(responseMessage(payload, 'Projekte konnten nicht geladen werden.'));
      const selected = adminProjectSelect?.value || projectSelect.value;
      projectSelect.replaceChildren();
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Projekt auswählen';
      projectSelect.appendChild(placeholder);
      (payload.items || []).forEach(project => {
        const option = document.createElement('option');
        option.value = String(project.id);
        option.textContent = project.name;
        projectSelect.appendChild(option);
      });
      if ([...projectSelect.options].some(option => option.value === String(selected))) {
        projectSelect.value = String(selected);
      }
    } catch (error) {
      showError(error.message);
    }
  }

  adminProjectSelect?.addEventListener('change', () => {
    if (!adminProjectSelect.value || pending) return;
    projectSelect.value = adminProjectSelect.value;
    const name = adminProjectSelect.options[adminProjectSelect.selectedIndex]?.textContent;
    filenameInput.value = safeSuggestedName(name);
  });

  projectSelect.addEventListener('change', () => {
    const name = projectSelect.options[projectSelect.selectedIndex]?.textContent;
    if (projectSelect.value) filenameInput.value = safeSuggestedName(name);
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    showError();
    if (!projectSelect.value) {
      showError('Bitte ein Projekt auswählen.');
      projectSelect.focus();
      return;
    }
    if (!filenameInput.value.trim()) {
      showError('Bitte einen Dateinamen eingeben.');
      filenameInput.focus();
      return;
    }
    if (!zipInput.checked) {
      showError('Der portable Export unterstützt den Download ausschließlich als ZIP.');
      zipInput.focus();
      return;
    }

    setPending(true);
    status.textContent = 'Tour wird zusammengestellt. Große Medien und Karten können einige Zeit benötigen …';
    try {
      const response = await fetch('/api/export/portable-tour', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: Number(projectSelect.value),
          filename: filenameInput.value,
          include_videos: videosInput.checked,
          include_map: mapInput.checked,
          include_tracks: tracksInput.checked
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(responseMessage(payload, `Export fehlgeschlagen (HTTP ${response.status}).`));
      }
      status.textContent = 'ZIP wird für den Download vorbereitet …';
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename="([^"]+)"/i);
      downloadBlob(blob, match?.[1] || 'portable-tour.zip');
      status.textContent = `Export abgeschlossen (${(blob.size / (1024 * 1024)).toFixed(1)} MiB).`;
    } catch (error) {
      status.textContent = 'Export fehlgeschlagen.';
      showError(error.message);
    } finally {
      setPending(false);
    }
  });

  loadProjects();
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !pending) loadProjects();
  });
}());
