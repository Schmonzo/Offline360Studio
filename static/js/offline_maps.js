(() => {
  'use strict';

  const form = document.getElementById('offlineMapImportForm');
  const fileInput = document.getElementById('offlineMapFile');
  const importButton = document.getElementById('offlineMapImportBtn');
  const list = document.getElementById('offlineMapList');
  const status = document.getElementById('offlineMapStatus');
  const basemapSelect = document.getElementById('mapBasemapSelect');
  const basemapStatus = document.getElementById('mapBasemapStatus');
  let sources = [];
  let pending = false;

  function setStatus(message, error = false) {
    if (!status) return;
    status.textContent = message;
    status.classList.toggle('inline-status--error', error);
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error?.message || `Anfrage fehlgeschlagen (${response.status}).`);
    }
    return data;
  }

  function button(label, className, handler) {
    const element = document.createElement('button');
    element.type = 'button';
    element.textContent = label;
    if (className) element.className = className;
    element.addEventListener('click', handler);
    return element;
  }

  function fileSize(bytes) {
    if (!Number.isFinite(bytes)) return 'Datei fehlt';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return `${value.toLocaleString('de-CH', { maximumFractionDigits: 1 })} ${units[index]}`;
  }

  function notifyMap() {
    window.dispatchEvent(new CustomEvent('offline-map-source-changed'));
  }

  function renderBasemapSelect() {
    const activeSource = sources.find(source => source.active) || null;
    if (!basemapSelect) return;
    basemapSelect.replaceChildren();
    const neutral = document.createElement('option');
    neutral.value = '';
    neutral.textContent = activeSource
      ? 'Keine Basiskarte'
      : 'Keine Basiskarte Â· Aktiv';
    basemapSelect.appendChild(neutral);
    sources.forEach(source => {
      const option = document.createElement('option');
      option.value = String(source.source_id);
      option.textContent = `${source.name} Â· ${window.mapSources.mapTypeLabel(source)}${source.active ? ' Â· Aktiv' : ''}`;
      basemapSelect.appendChild(option);
    });
    basemapSelect.value = activeSource ? String(activeSource.source_id) : '';
    if (basemapStatus) {
      basemapStatus.textContent = activeSource
        ? `Aktiv: ${activeSource.name} Â· ${window.mapSources.mapTypeLabel(activeSource)}`
        : 'Aktiv: Keine Basiskarte Â· neutraler Hintergrund';
    }
  }

  async function updateSource(source, payload, message) {
    try {
      await requestJson(`/api/maps/sources/${source.source_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      setStatus(message);
      await loadSources();
      if (Object.hasOwn(payload, 'active')) notifyMap();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function renderSource(source) {
    const row = document.createElement('article');
    row.className = 'offline-map-source';

    const heading = document.createElement('div');
    heading.className = 'offline-map-source__heading';
    const state = document.createElement('strong');
    state.textContent = source.active ? 'Aktiv' : 'Inaktiv';
    state.classList.toggle('offline-map-source__active', source.active);
    const details = document.createElement('span');
    const zoom = source.min_zoom === null && source.max_zoom === null
      ? 'Zoom unbekannt'
      : `Zoom ${source.min_zoom ?? 'â€“'}â€“${source.max_zoom ?? 'â€“'}`;
    const schema = source.schema_type === 'normalized' ? 'Normalisiert' : 'Flat';
    details.textContent = `${window.mapSources.mapTypeLabel(source)} Â· ${String(source.format).toUpperCase()} Â· ${schema} Â· ${zoom} Â· ${fileSize(source.file_size)}`;
    heading.append(state, details);
    if (window.mapSources.mapType(source) === 'vector') {
      const layerInfo = document.createElement('span');
      const count = Array.isArray(source.vector_layers) ? source.vector_layers.length : 0;
      layerInfo.textContent = count === 1
        ? '1 Vector-Layer erkannt'
        : `${count} Vector-Layer erkannt`;
      heading.appendChild(layerInfo);
      if (!source.style_available) {
        const warning = document.createElement('p');
        warning.className = 'offline-map-warning';
        warning.textContent = 'Keine vector_layers in metadata.json gefunden. Der automatische Basisstil kann keine Kartenobjekte zuordnen.';
        heading.appendChild(warning);
      }
    }

    const rename = document.createElement('form');
    rename.className = 'offline-map-rename';
    const label = document.createElement('label');
    label.textContent = 'Name';
    const input = document.createElement('input');
    input.type = 'text';
    input.maxLength = 200;
    input.required = true;
    input.value = source.name;
    label.appendChild(input);
    const renameButton = document.createElement('button');
    renameButton.type = 'submit';
    renameButton.textContent = 'Umbenennen';
    rename.append(label, renameButton);
    rename.addEventListener('submit', event => {
      event.preventDefault();
      updateSource(source, { name: input.value }, `${input.value.trim()} wurde umbenannt.`);
    });

    const actions = document.createElement('div');
    actions.className = 'offline-map-actions';
    if (!source.active) {
      actions.appendChild(button('Aktivieren', '', () => {
        updateSource(source, { active: true }, `${source.name} ist jetzt aktiv.`);
      }));
    }
    const deleteButton = button('LÃ¶schen', 'danger', () => {
      if (deleteButton.dataset.confirm !== 'true') {
        deleteButton.dataset.confirm = 'true';
        deleteButton.textContent = 'LÃ¶schen bestÃ¤tigen';
        setStatus(`LÃ¶schen von ${source.name} durch erneutes DrÃ¼cken bestÃ¤tigen.`);
        return;
      }
      deleteSource(source);
    });
    deleteButton.addEventListener('blur', () => {
      deleteButton.dataset.confirm = 'false';
      deleteButton.textContent = 'LÃ¶schen';
    });
    actions.appendChild(deleteButton);
    row.append(heading, rename, actions);
    return row;
  }

  function render() {
    renderBasemapSelect();
    if (!list) return;
    list.replaceChildren();
    if (!sources.length) {
      const empty = document.createElement('p');
      empty.textContent = 'Noch keine Offline-Karte importiert.';
      list.appendChild(empty);
      return;
    }
    sources.forEach(source => list.appendChild(renderSource(source)));
  }

  async function loadSources() {
    try {
      const data = await requestJson('/api/maps/sources');
      sources = window.mapSources.normalize(data.items);
      render();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function selectBasemap() {
    if (!basemapSelect) return;
    const selectedValue = basemapSelect.value;
    const sourceId = selectedValue === '' ? null : Number(selectedValue);
    if (sourceId !== null && !sources.some(source => source.source_id === sourceId)) {
      setStatus('Die gewÃ¤hlte Kartenquelle ist nicht mehr verfÃ¼gbar.', true);
      renderBasemapSelect();
      return;
    }
    basemapSelect.disabled = true;
    if (basemapStatus) basemapStatus.textContent = 'Basiskarte wird gewechselt â€¦';
    try {
      await requestJson('/api/maps/active', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: sourceId })
      });
      await loadSources();
      notifyMap();
    } catch (error) {
      setStatus(error.message, true);
      await loadSources();
    } finally {
      basemapSelect.disabled = false;
    }
  }

  async function deleteSource(source) {
    try {
      await requestJson(`/api/maps/sources/${source.source_id}`, { method: 'DELETE' });
      setStatus(`${source.name} wurde gelÃ¶scht.`);
      await loadSources();
      if (source.active) notifyMap();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  if (form && fileInput && importButton) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const file = fileInput.files?.[0];
      if (!file || pending) {
        setStatus('Bitte zuerst eine .mbtiles-Datei auswÃ¤hlen.', true);
        fileInput.focus();
        return;
      }
      pending = true;
      importButton.disabled = true;
      fileInput.disabled = true;
      setStatus('MBTiles-Datei wird geprÃ¼ft und importiert â€¦');
      const body = new FormData();
      body.append('file', file);
      try {
        const data = await requestJson('/api/maps/sources/import', {
          method: 'POST',
          body
        });
        fileInput.value = '';
        setStatus(`${data.item.name} wurde importiert.`);
        await loadSources();
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        pending = false;
        importButton.disabled = false;
        fileInput.disabled = false;
      }
    });
  }
  basemapSelect?.addEventListener('change', selectBasemap);

  window.offlineMapsUi = { refresh: loadSources };
  loadSources();
})();

