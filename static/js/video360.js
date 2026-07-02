// Spherical equirectangular MP4 viewer.
// Three.js is loaded on demand from the local offline bundle.
(function () {
  'use strict';

  const THREE_MODULE_URL = '/static/lib/three.module.min.js';
  const MIN_FOV = 25;
  const MAX_FOV = 100;
  const ZOOM_FACTOR = 0.85;
  const KEYBOARD_LOOK_STEP = 5;

  let threeModulePromise = null;

  function loadThree() {
    if (!threeModulePromise) {
      threeModulePromise = import(THREE_MODULE_URL);
    }
    return threeModulePromise;
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const totalSeconds = Math.floor(seconds);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    const base = `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
    return hours ? `${hours}:${base}` : base;
  }

  function mediaErrorMessage(error) {
    if (!error) {
      return 'Das 360°-Video konnte nicht geladen werden.';
    }
    if (error.code === 4) {
      return 'Dieses MP4 oder sein Video-/Audio-Codec wird vom Browser nicht unterstützt.';
    }
    if (error.code === 2) {
      return 'Das 360°-Video konnte wegen eines Lade- oder Netzwerkfehlers nicht gelesen werden.';
    }
    if (error.code === 3) {
      return 'Das MP4 konnte nicht dekodiert werden. Der Codec ist möglicherweise nicht unterstützt oder die Datei ist beschädigt.';
    }
    if (error.code === 1) {
      return 'Das Laden des 360°-Videos wurde abgebrochen.';
    }
    return 'Das 360°-Video konnte nicht geladen werden.';
  }

  class Video360Viewer {
    constructor(container, sourceUrl, options = {}) {
      this.container = container;
      this.sourceUrl = sourceUrl;
      this.fullscreenElement = options.fullscreenElement || container;
      this.onViewChange = typeof options.onViewChange === 'function'
        ? options.onViewChange
        : null;
      this.destroyed = false;
      this.listeners = [];
      this.pointers = new Map();
      this.longitude = -90;
      this.latitude = 0;
      this.fov = 75;
      this.animationFrame = null;
      this.lastPinchDistance = null;

      this.buildDom();
      this.bindMediaEvents();
      this.bindInteractionEvents();
      this.initialize();
    }

    buildDom() {
      this.root = document.createElement('div');
      this.root.className = 'video360';
      this.root.tabIndex = 0;
      this.root.setAttribute('role', 'application');
      this.root.setAttribute(
        'aria-label',
        '360-Grad-Video. Ziehen zum Umsehen, Mausrad oder Pinch zum Zoomen.'
      );

      this.canvasHost = document.createElement('div');
      this.canvasHost.className = 'video360__canvas-host';

      this.video = document.createElement('video');
      this.video.className = 'video360__source';
      this.video.preload = 'metadata';
      this.video.playsInline = true;
      this.video.loop = true;
      this.video.crossOrigin = 'anonymous';

      this.status = document.createElement('div');
      this.status.className = 'video360__status';
      this.status.setAttribute('role', 'status');
      this.status.textContent = '360°-Video wird geladen …';

      this.controls = document.createElement('div');
      this.controls.className = 'video360__controls';
      this.controls.setAttribute('aria-label', 'Video-Steuerung');

      this.playButton = document.createElement('button');
      this.playButton.type = 'button';
      this.playButton.className = 'video360__play';
      this.playButton.textContent = '▶';
      this.playButton.title = 'Wiedergabe/Pause (Leertaste)';
      this.playButton.setAttribute('aria-label', 'Wiedergabe starten');

      this.timeline = document.createElement('input');
      this.timeline.className = 'video360__timeline';
      this.timeline.type = 'range';
      this.timeline.min = '0';
      this.timeline.max = '0';
      this.timeline.step = '0.01';
      this.timeline.value = '0';
      this.timeline.setAttribute('aria-label', 'Zeitleiste');

      this.time = document.createElement('span');
      this.time.className = 'video360__time';
      this.time.textContent = '00:00 / 00:00';

      this.volume = document.createElement('input');
      this.volume.className = 'video360__volume';
      this.volume.type = 'range';
      this.volume.min = '0';
      this.volume.max = '1';
      this.volume.step = '0.05';
      this.volume.value = '1';
      this.volume.setAttribute('aria-label', 'Lautstärke');

      this.fullscreenButton = document.createElement('button');
      this.fullscreenButton.type = 'button';
      this.fullscreenButton.textContent = 'Vollbild';
      this.fullscreenButton.title = 'Vollbild';

      this.controls.append(
        this.playButton,
        this.timeline,
        this.time,
        this.volume,
        this.fullscreenButton
      );
      this.root.append(this.canvasHost, this.video, this.status, this.controls);
      this.container.replaceChildren(this.root);
      this.container.closest('.stage')?.classList.add('video-mode');
    }

    listen(target, eventName, handler, options) {
      target.addEventListener(eventName, handler, options);
      this.listeners.push(() => target.removeEventListener(eventName, handler, options));
    }

    bindMediaEvents() {
      this.listen(this.playButton, 'click', () => this.togglePlay());
      this.listen(this.fullscreenButton, 'click', () => this.toggleFullscreen());
      this.listen(this.timeline, 'input', () => {
        if (Number.isFinite(this.video.duration)) {
          this.video.currentTime = Number(this.timeline.value);
        }
      });
      this.listen(this.volume, 'input', () => {
        this.video.volume = Number(this.volume.value);
        this.video.muted = this.video.volume === 0;
      });
      this.listen(this.video, 'loadedmetadata', () => this.updateMediaControls());
      this.listen(this.video, 'durationchange', () => this.updateMediaControls());
      this.listen(this.video, 'timeupdate', () => this.updateMediaControls());
      this.listen(this.video, 'canplay', () => this.clearStatus());
      this.listen(this.video, 'play', () => this.updatePlayButton());
      this.listen(this.video, 'pause', () => {
        this.updatePlayButton();
        if (this.video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
          this.clearStatus();
        }
      });
      this.listen(this.video, 'playing', () => this.clearStatus());
      this.listen(this.video, 'loadeddata', () => this.clearStatus());
      this.listen(this.video, 'volumechange', () => {
        this.volume.value = String(this.video.muted ? 0 : this.video.volume);
      });
      this.listen(this.video, 'waiting', () => this.showStatus('Video wird gepuffert …'));
      this.listen(this.video, 'error', () => this.showError(mediaErrorMessage(this.video.error)));
      this.listen(document, 'fullscreenchange', () => {
        this.resize();
        this.fullscreenButton.textContent = document.fullscreenElement
          ? 'Vollbild aus'
          : 'Vollbild';
      });
    }

    bindInteractionEvents() {
      this.listen(this.root, 'pointerdown', event => this.onPointerDown(event));
      this.listen(this.root, 'pointermove', event => this.onPointerMove(event));
      this.listen(this.root, 'pointerup', event => this.onPointerEnd(event));
      this.listen(this.root, 'pointercancel', event => this.onPointerEnd(event));
      this.listen(this.root, 'wheel', event => {
        if (event.target.closest('.video360__controls')) return;
        event.preventDefault();
        this.setFov(this.fov + event.deltaY * 0.05);
      }, { passive: false });
      this.listen(window, 'resize', () => this.resize());
    }

    async initialize() {
      try {
        const THREE = await loadThree();
        if (this.destroyed) return;
        this.THREE = THREE;
        this.createWebGLScene();
        this.video.src = this.sourceUrl;
        this.video.load();
        this.render();

        try {
          await this.video.play();
        } catch (error) {
          if (!this.destroyed && error?.name !== 'AbortError') {
            this.showStatus('Wiedergabe ist pausiert. Zum Starten ▶ wählen.');
          }
        }
      } catch (error) {
        if (!this.destroyed) {
          console.error('360°-Video-Initialisierung fehlgeschlagen:', error);
          this.showError(
            error?.message?.toLowerCase().includes('webgl')
              ? 'WebGL ist nicht verfügbar oder wurde vom Browser deaktiviert.'
              : 'Der lokale Three.js-Renderer konnte nicht geladen werden.'
          );
        }
      }
    }

    createWebGLScene() {
      const THREE = this.THREE;
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(this.fov, 1, 0.1, 2000);
      this.camera.position.set(0, 0, 0);

      this.renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: 'high-performance'
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setClearColor(0x000000, 1);
      this.renderer.domElement.className = 'video360__canvas';
      this.renderer.domElement.setAttribute('aria-hidden', 'true');
      this.canvasHost.append(this.renderer.domElement);

      this.texture = new THREE.VideoTexture(this.video);
      this.texture.colorSpace = THREE.SRGBColorSpace;
      this.texture.minFilter = THREE.LinearFilter;
      this.texture.magFilter = THREE.LinearFilter;
      this.texture.generateMipmaps = false;

      this.geometry = new THREE.SphereGeometry(500, 64, 40);
      this.geometry.scale(-1, 1, 1);
      this.material = new THREE.MeshBasicMaterial({ map: this.texture });
      this.sphere = new THREE.Mesh(this.geometry, this.material);
      this.scene.add(this.sphere);

      this.listen(this.renderer.domElement, 'webglcontextlost', event => {
        event.preventDefault();
        this.showError('Der WebGL-Kontext ging verloren. Bitte das Video erneut öffnen.');
      });

      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(this.container);
      }
      this.resize();
      this.updateCamera();
    }

    render() {
      if (this.destroyed || !this.renderer) return;
      this.renderer.render(this.scene, this.camera);
      this.animationFrame = requestAnimationFrame(() => this.render());
    }

    resize() {
      if (!this.renderer || !this.camera || this.destroyed) return;
      const width = Math.max(1, this.container.clientWidth);
      const height = Math.max(1, this.container.clientHeight);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setSize(width, height, false);
    }

    onPointerDown(event) {
      if (event.target.closest('.video360__controls')) return;
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault();
      this.root.focus({ preventScroll: true });
      this.root.setPointerCapture?.(event.pointerId);
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (this.pointers.size === 2) {
        this.lastPinchDistance = this.pointerDistance();
      }
      this.root.classList.add('video360--dragging');
    }

    onPointerMove(event) {
      const previous = this.pointers.get(event.pointerId);
      if (!previous) return;
      event.preventDefault();
      const current = { x: event.clientX, y: event.clientY };
      this.pointers.set(event.pointerId, current);

      if (this.pointers.size === 1) {
        this.longitude -= (current.x - previous.x) * 0.12;
        this.latitude += (current.y - previous.y) * 0.12;
        this.latitude = Math.max(-85, Math.min(85, this.latitude));
        this.updateCamera();
      } else if (this.pointers.size === 2) {
        const distance = this.pointerDistance();
        if (this.lastPinchDistance && distance > 0) {
          this.setFov(this.fov * (this.lastPinchDistance / distance));
        }
        this.lastPinchDistance = distance;
      }
    }

    onPointerEnd(event) {
      this.pointers.delete(event.pointerId);
      if (this.pointers.size < 2) this.lastPinchDistance = null;
      if (this.pointers.size === 0) this.root.classList.remove('video360--dragging');
      try {
        if (this.root.hasPointerCapture?.(event.pointerId)) {
          this.root.releasePointerCapture(event.pointerId);
        }
      } catch (error) {
        console.warn('Pointer-Capture konnte nicht freigegeben werden:', error);
      }
    }

    pointerDistance() {
      const points = [...this.pointers.values()];
      if (points.length < 2) return 0;
      return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
    }

    updateCamera() {
      if (!this.camera || !this.THREE) return;
      const phi = this.THREE.MathUtils.degToRad(90 - this.latitude);
      const theta = this.THREE.MathUtils.degToRad(this.longitude);
      this.camera.lookAt(
        500 * Math.sin(phi) * Math.cos(theta),
        500 * Math.cos(phi),
        500 * Math.sin(phi) * Math.sin(theta)
      );
      this.onViewChange?.();
    }

    setFov(fov) {
      this.fov = Math.max(MIN_FOV, Math.min(MAX_FOV, fov));
      if (this.camera) {
        this.camera.fov = this.fov;
        this.camera.updateProjectionMatrix();
      }
      this.onViewChange?.();
    }

    zoomIn() {
      this.setFov(this.fov * ZOOM_FACTOR);
    }

    zoomOut() {
      this.setFov(this.fov / ZOOM_FACTOR);
    }

    lookBy(yaw, pitch) {
      this.longitude += yaw * KEYBOARD_LOOK_STEP;
      this.latitude = Math.max(
        -85,
        Math.min(85, this.latitude + pitch * KEYBOARD_LOOK_STEP)
      );
      this.updateCamera();
    }

    resetView() {
      this.longitude = -90;
      this.latitude = 0;
      this.setFov(75);
      this.updateCamera();
    }

    getZoomPercent() {
      return Math.round(((MAX_FOV - this.fov) / (MAX_FOV - MIN_FOV)) * 100);
    }

    async togglePlay() {
      if (this.destroyed || !this.video.src) return;
      if (!this.video.paused) {
        this.video.pause();
        return;
      }
      try {
        await this.video.play();
      } catch (error) {
        if (error?.name !== 'AbortError') {
          if (this.video.error) {
            this.showError(mediaErrorMessage(this.video.error));
          } else {
            this.showStatus('Wiedergabe konnte nicht gestartet werden.');
          }
        }
      }
    }

    async toggleFullscreen() {
      try {
        if (document.fullscreenElement) {
          await document.exitFullscreen?.();
        } else {
          await this.fullscreenElement.requestFullscreen?.();
        }
      } catch (error) {
        this.showError('Vollbild konnte vom Browser nicht aktiviert werden.');
      }
    }

    updatePlayButton() {
      const playing = !this.video.paused && !this.video.ended;
      this.playButton.textContent = playing ? '❚❚' : '▶';
      this.playButton.setAttribute(
        'aria-label',
        playing ? 'Wiedergabe pausieren' : 'Wiedergabe starten'
      );
    }

    updateMediaControls() {
      const duration = Number.isFinite(this.video.duration) ? this.video.duration : 0;
      this.timeline.max = String(duration);
      this.timeline.value = String(Math.min(this.video.currentTime || 0, duration));
      this.time.textContent = `${formatTime(this.video.currentTime)} / ${formatTime(duration)}`;
      this.timeline.setAttribute('aria-valuetext', this.time.textContent);
    }

    showStatus(message) {
      if (this.status.classList.contains('video360__status--error')) return;
      this.status.textContent = message;
      this.status.hidden = false;
    }

    clearStatus() {
      if (!this.status.classList.contains('video360__status--error')) {
        this.status.hidden = true;
      }
    }

    showError(message) {
      this.status.textContent = message;
      this.status.hidden = false;
      this.status.classList.add('video360__status--error');
      this.status.setAttribute('role', 'alert');
      this.video.pause();
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.listeners.splice(0).forEach(remove => remove());
      this.video.pause();
      this.video.removeAttribute('src');
      this.video.load();
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
      this.resizeObserver?.disconnect();
      this.resizeObserver = null;
      this.pointers.clear();

      if (this.scene && this.sphere) this.scene.remove(this.sphere);
      this.texture?.dispose();
      this.material?.dispose();
      this.geometry?.dispose();
      this.renderer?.renderLists?.dispose();
      this.renderer?.dispose();
      this.renderer?.forceContextLoss();
      this.container.closest('.stage')?.classList.remove('video-mode');
      this.root.remove();

      this.sphere = null;
      this.texture = null;
      this.material = null;
      this.geometry = null;
      this.scene = null;
      this.camera = null;
      this.renderer = null;
    }
  }

  window.Video360Viewer = Video360Viewer;
})();
