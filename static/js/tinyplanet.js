// Stereographic Tiny Planet renderer for equirectangular photos.
// Three.js is loaded on demand from the local offline bundle.
(function () {
  'use strict';

  const THREE_MODULE_URL = '/static/lib/three.module.min.js';
  const MIN_ZOOM = 0.35;
  const MAX_ZOOM = 2.2;
  const DEFAULT_ZOOM = 0.82;
  const MAX_TILT = Math.PI * 0.22;

  let threeModulePromise = null;

  function loadThree() {
    if (!threeModulePromise) {
      threeModulePromise = import(THREE_MODULE_URL);
    }
    return threeModulePromise;
  }

  class TinyPlanetRenderer {
    constructor(container, imageUrl, options = {}) {
      this.container = container;
      this.imageUrl = imageUrl;
      this.initialYaw = Number.isFinite(options.yaw) ? options.yaw : 0;
      this.onViewChange = typeof options.onViewChange === 'function'
        ? options.onViewChange
        : null;
      this.onError = typeof options.onError === 'function'
        ? options.onError
        : null;
      this.destroyed = false;
      this.listeners = [];
      this.pointers = new Map();
      this.animationFrame = null;
      this.lastPinchDistance = null;
      this.yaw = this.initialYaw;
      this.tilt = 0;
      this.zoom = DEFAULT_ZOOM;

      this.buildDom();
      this.bindInteractionEvents();
      this.initialize();
    }

    buildDom() {
      this.root = document.createElement('div');
      this.root.className = 'tinyplanet';
      this.root.tabIndex = 0;
      this.root.setAttribute('role', 'application');
      this.root.setAttribute(
        'aria-label',
        'Tiny-Planet-Ansicht. Ziehen zum Drehen, Mausrad oder Pinch zum Zoomen.'
      );

      this.canvasHost = document.createElement('div');
      this.canvasHost.className = 'tinyplanet__canvas-host';

      this.status = document.createElement('div');
      this.status.className = 'tinyplanet__status';
      this.status.setAttribute('role', 'status');
      this.status.textContent = 'Tiny Planet wird geladen …';

      this.root.append(this.canvasHost, this.status);
      this.container.append(this.root);
    }

    listen(target, eventName, handler, options) {
      target.addEventListener(eventName, handler, options);
      this.listeners.push(() => target.removeEventListener(eventName, handler, options));
    }

    bindInteractionEvents() {
      this.listen(this.root, 'pointerdown', event => this.onPointerDown(event));
      this.listen(this.root, 'pointermove', event => this.onPointerMove(event));
      this.listen(this.root, 'pointerup', event => this.onPointerEnd(event));
      this.listen(this.root, 'pointercancel', event => this.onPointerEnd(event));
      this.listen(this.root, 'wheel', event => {
        event.preventDefault();
        this.setZoom(this.zoom * Math.exp(-event.deltaY * 0.001));
      }, { passive: false });
      this.listen(window, 'resize', () => this.resize());
    }

    async initialize() {
      try {
        this.initializationPhase = 'three';
        const THREE = await loadThree();
        if (this.destroyed) return;
        this.THREE = THREE;
        this.initializationPhase = 'webgl';
        this.createWebGLScene();
        this.initializationPhase = 'texture';
        this.texture = await this.loadTexture();
        if (this.destroyed) {
          this.texture.dispose();
          this.texture = null;
          return;
        }
        this.material.uniforms.panorama.value = this.texture;
        this.material.uniforms.textureReady.value = 1;
        this.status.hidden = true;
        this.render();
      } catch (error) {
        if (this.destroyed) return;
        console.error('Tiny-Planet-Initialisierung fehlgeschlagen:', error);
        const message = this.initializationPhase === 'webgl'
          ? 'WebGL ist nicht verfügbar oder wurde vom Browser deaktiviert.'
          : this.initializationPhase === 'texture'
            ? 'Die Bildtextur für Tiny Planet konnte nicht geladen werden.'
            : 'Der lokale Three.js-Renderer konnte nicht geladen werden.';
        this.status.textContent = message;
        this.status.classList.add('tinyplanet__status--error');
        this.status.setAttribute('role', 'alert');
        this.onError?.(message);
      }
    }

    createWebGLScene() {
      const THREE = this.THREE;
      this.scene = new THREE.Scene();
      this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      this.renderer = new THREE.WebGLRenderer({
        antialias: true,
        powerPreference: 'high-performance'
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setClearColor(0x050608, 1);
      this.renderer.domElement.className = 'tinyplanet__canvas';
      this.renderer.domElement.setAttribute('aria-hidden', 'true');
      this.canvasHost.append(this.renderer.domElement);

      this.material = new THREE.ShaderMaterial({
        depthTest: false,
        depthWrite: false,
        uniforms: {
          panorama: { value: null },
          textureReady: { value: 0 },
          aspect: { value: 1 },
          zoom: { value: this.zoom },
          yaw: { value: this.yaw },
          tilt: { value: this.tilt }
        },
        vertexShader: [
          'varying vec2 vUv;',
          'void main() {',
          '  vUv = uv;',
          '  gl_Position = vec4(position.xy, 0.0, 1.0);',
          '}'
        ].join('\n'),
        fragmentShader: [
          'precision highp float;',
          'uniform sampler2D panorama;',
          'uniform float textureReady;',
          'uniform float aspect;',
          'uniform float zoom;',
          'uniform float yaw;',
          'uniform float tilt;',
          'varying vec2 vUv;',
          'const float PI = 3.141592653589793;',
          'void main() {',
          '  if (textureReady < 0.5) {',
          '    gl_FragColor = vec4(0.02, 0.024, 0.032, 1.0);',
          '    return;',
          '  }',
          '  vec2 plane = (vUv - 0.5) * 2.0;',
          '  plane.x *= aspect;',
          '  plane /= zoom;',
          '  float radius2 = dot(plane, plane);',
          '  float denominator = 1.0 + radius2;',
          '  vec3 direction = vec3(',
          '    2.0 * plane.x / denominator,',
          '    -(1.0 - radius2) / denominator,',
          '    2.0 * plane.y / denominator',
          '  );',
          '  float cosTilt = cos(tilt);',
          '  float sinTilt = sin(tilt);',
          '  direction = vec3(',
          '    direction.x,',
          '    direction.y * cosTilt - direction.z * sinTilt,',
          '    direction.y * sinTilt + direction.z * cosTilt',
          '  );',
          '  float longitude = atan(direction.x, -direction.z) + yaw;',
          '  float latitude = asin(clamp(direction.y, -1.0, 1.0));',
          '  vec2 panoramaUv = vec2(',
          '    fract(0.5 + longitude / (2.0 * PI)),',
          '    clamp(0.5 - latitude / PI, 0.0, 1.0)',
          '  );',
          '  gl_FragColor = texture2D(panorama, panoramaUv);',
          '}'
        ].join('\n')
      });

      this.geometry = new THREE.PlaneGeometry(2, 2);
      this.quad = new THREE.Mesh(this.geometry, this.material);
      this.scene.add(this.quad);

      this.listen(this.renderer.domElement, 'webglcontextlost', event => {
        event.preventDefault();
        this.onError?.('Der WebGL-Kontext ging verloren. Tiny Planet wurde beendet.');
      });

      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(this.container);
      }
      this.resize();
    }

    loadTexture() {
      return new Promise((resolve, reject) => {
        const loader = new this.THREE.TextureLoader();
        loader.load(
          this.imageUrl,
          texture => {
            texture.colorSpace = this.THREE.SRGBColorSpace;
            texture.wrapS = this.THREE.RepeatWrapping;
            texture.minFilter = this.THREE.LinearFilter;
            texture.magFilter = this.THREE.LinearFilter;
            texture.generateMipmaps = false;
            resolve(texture);
          },
          undefined,
          () => reject(new Error('Texture load failed'))
        );
      });
    }

    render() {
      if (this.destroyed || !this.renderer) return;
      this.renderer.render(this.scene, this.camera);
      this.animationFrame = requestAnimationFrame(() => this.render());
    }

    resize() {
      if (!this.renderer || this.destroyed) return;
      const width = Math.max(1, this.container.clientWidth);
      const height = Math.max(1, this.container.clientHeight);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setSize(width, height, false);
      this.material.uniforms.aspect.value = width / height;
    }

    onPointerDown(event) {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault();
      this.root.focus({ preventScroll: true });
      this.root.setPointerCapture?.(event.pointerId);
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (this.pointers.size === 2) {
        this.lastPinchDistance = this.pointerDistance();
      }
      this.root.classList.add('tinyplanet--dragging');
    }

    onPointerMove(event) {
      const previous = this.pointers.get(event.pointerId);
      if (!previous) return;
      event.preventDefault();
      const current = { x: event.clientX, y: event.clientY };
      this.pointers.set(event.pointerId, current);

      if (this.pointers.size === 1) {
        this.yaw += (current.x - previous.x) * 0.006;
        this.tilt = Math.max(
          -MAX_TILT,
          Math.min(MAX_TILT, this.tilt + (current.y - previous.y) * 0.003)
        );
        this.updateUniforms();
      } else if (this.pointers.size === 2) {
        const distance = this.pointerDistance();
        if (this.lastPinchDistance && distance > 0) {
          this.setZoom(this.zoom * (distance / this.lastPinchDistance));
        }
        this.lastPinchDistance = distance;
      }
    }

    onPointerEnd(event) {
      this.pointers.delete(event.pointerId);
      if (this.pointers.size < 2) this.lastPinchDistance = null;
      if (this.pointers.size === 0) this.root.classList.remove('tinyplanet--dragging');
      try {
        if (this.root.hasPointerCapture?.(event.pointerId)) {
          this.root.releasePointerCapture(event.pointerId);
        }
      } catch (error) {
        console.warn('Tiny-Planet Pointer-Capture konnte nicht freigegeben werden:', error);
      }
    }

    pointerDistance() {
      const points = [...this.pointers.values()];
      if (points.length < 2) return 0;
      return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
    }

    updateUniforms() {
      if (!this.material) return;
      this.material.uniforms.yaw.value = this.yaw;
      this.material.uniforms.tilt.value = this.tilt;
      this.material.uniforms.zoom.value = this.zoom;
      this.onViewChange?.();
    }

    setZoom(zoom) {
      this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
      this.updateUniforms();
    }

    zoomIn() {
      this.setZoom(this.zoom * 1.15);
    }

    zoomOut() {
      this.setZoom(this.zoom / 1.15);
    }

    resetView() {
      this.yaw = this.initialYaw;
      this.tilt = 0;
      this.zoom = DEFAULT_ZOOM;
      this.updateUniforms();
    }

    getZoomPercent() {
      return Math.round(((this.zoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM)) * 100);
    }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.listeners.splice(0).forEach(remove => remove());
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
      this.resizeObserver?.disconnect();
      this.resizeObserver = null;
      this.pointers.clear();

      if (this.scene && this.quad) this.scene.remove(this.quad);
      this.texture?.dispose();
      this.material?.dispose();
      this.geometry?.dispose();
      this.renderer?.renderLists?.dispose();
      this.renderer?.dispose();
      this.renderer?.forceContextLoss();
      this.root.remove();

      this.quad = null;
      this.texture = null;
      this.material = null;
      this.geometry = null;
      this.scene = null;
      this.camera = null;
      this.renderer = null;
    }
  }

  window.TinyPlanetRenderer = TinyPlanetRenderer;
})();
