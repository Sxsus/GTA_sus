(function (global) {
  'use strict';

  const DEFAULT_API_KEY = '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';
  const GROQ_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions';
  const DEFAULT_MODEL = 'llama-3.3-70b-versatile';

  const DEFAULT_CONFIG = {
    targetFps: 60,
    minScale: 0.55,
    maxScale: 1.0,
    maxPixelRatio: 2.0,
    drawDistance: 240,
    maxActiveNpc: 48,
    maxActiveVehicles: 36,
    maxRagdollParts: 48,
    maxParticles: 260,
    cloudDensity: 0.75,
    shadowMapSize: 2048,
    exposure: 1.08,
    fogDensity: 0.0014,
    aiIntervalMs: 12000,
    aiEnabled: true,
    autoTune: true,
    showOverlay: true
  };

  function clamp(val, min, max, fallback = min) {
    const num = Number(val);
    if (!Number.isFinite(num)) return fallback;
    return Math.min(max, Math.max(min, num));
  }

  function hashState(obj) {
    const str = JSON.stringify(obj);
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16);
  }

  class GtaSusOptimizer {
    constructor(options = {}) {
      this.apiKey = options.apiKey || DEFAULT_API_KEY;
      this.model = options.model || DEFAULT_MODEL;
      this.config = Object.assign({}, DEFAULT_CONFIG, options);

      this.renderer = null;
      this.scene = null;
      this.camera = null;
      this.refs = {};

      this.scale = this.config.maxScale;
      this.fps = 60;
      this.frameTimeMs = 16.67;
      this.smoothFrameMs = 16.67;
      this.lastFrameTime = performance.now();
      this.lastAiCall = 0;
      this.aiBusy = false;
      this.aiStatus = 'Gotowy (AI + Offline)';
      this.lastAiReason = 'Inicjalizacja optymalizatora';
      this.cache = new Map();

      this.stats = {
        culledObjects: 0,
        culledNpc: 0,
        culledVehicles: 0,
        activeRagdoll: 0,
        activeParticles: 0,
        aiCalls: 0,
        cacheHits: 0
      };

      this._frustum = null;
      this._projScreenMatrix = null;
      this._box = null;
      this._overlayEl = null;
      this._statusEl = null;

      this.initThreeHelpers();
      if (this.config.showOverlay && typeof document !== 'undefined') {
        this.mountOverlay();
      }
    }

    initThreeHelpers() {
      const THREE = global.THREE;
      if (THREE && THREE.Frustum && THREE.Matrix4 && THREE.Box3) {
        this._frustum = new THREE.Frustum();
        this._projScreenMatrix = new THREE.Matrix4();
        this._box = new THREE.Box3();
      }
    }

    attach(context = {}) {
      this.initThreeHelpers();
      if (context.renderer) this.renderer = context.renderer;
      if (context.scene) this.scene = context.scene;
      if (context.camera) this.camera = context.camera;
      if (context.refs) {
        this.refs = Object.assign({}, this.refs, context.refs);
      }
      this.applyGraphicsSettings();
      this.applyRenderScale(this.scale);
      return this;
    }

    setApiKey(key) {
      if (typeof key === 'string' && key.trim().length > 10) {
        this.apiKey = key.trim();
        this.aiStatus = 'Klucz AI zaktualizowany';
      }
    }

    applyRenderScale(newScale) {
      this.scale = clamp(newScale, this.config.minScale, this.config.maxScale, this.config.maxScale);
      if (!this.renderer || typeof window === 'undefined') return;

      const dpr = Math.min(window.devicePixelRatio || 1, this.config.maxPixelRatio);
      const effectiveDpr = Math.max(0.5, dpr * this.scale);
      if (typeof this.renderer.setPixelRatio === 'function') {
        this.renderer.setPixelRatio(effectiveDpr);
      }
      if (typeof this.renderer.getSize === 'function' && typeof this.renderer.setSize === 'function') {
        const THREE = global.THREE;
        const size = this.renderer.getSize(new THREE.Vector2());
        const w = Math.max(1, size.x || window.innerWidth);
        const h = Math.max(1, size.y || window.innerHeight);
        this.renderer.setSize(w, h, false);
      }
    }

    applyGraphicsSettings() {
      const THREE = global.THREE;
      if (this.renderer) {
        if ('toneMappingExposure' in this.renderer) {
          this.renderer.toneMappingExposure = clamp(this.config.exposure, 0.5, 2.2, 1.08);
        }
        if (this.renderer.shadowMap && THREE) {
          this.renderer.shadowMap.enabled = this.config.shadowMapSize > 0;
          this.renderer.shadowMap.type = THREE.PCFSoftShadowMap || this.renderer.shadowMap.type;
        }
      }

      if (this.scene && this.scene.fog && 'density' in this.scene.fog) {
        this.scene.fog.density = clamp(this.config.fogDensity, 0.0001, 0.02, 0.0014);
      }

      const clouds = this.refs.clouds || (this.scene && this.scene.userData && this.scene.userData.clouds);
      if (Array.isArray(clouds) && clouds.length > 0) {
        const targetCount = Math.round(clouds.length * clamp(this.config.cloudDensity, 0, 1, 0.75));
        clouds.forEach((cloud, idx) => {
          if (cloud) cloud.visible = idx < targetCount;
        });
      }
    }

    autoTuneByFrameTime(dtMs) {
      const targetMs = 1000 / clamp(this.config.targetFps, 24, 144, 60);
      const ratio = dtMs / targetMs;

      if (ratio > 1.25) {
        this.scale = clamp(this.scale - 0.04, this.config.minScale, this.config.maxScale, this.scale);
        this.config.drawDistance = Math.max(110, this.config.drawDistance - 10);
        this.config.maxActiveNpc = Math.max(16, this.config.maxActiveNpc - 2);
        this.config.maxActiveVehicles = Math.max(12, this.config.maxActiveVehicles - 2);
        this.config.maxParticles = Math.max(80, this.config.maxParticles - 25);
        this.applyRenderScale(this.scale);
      } else if (ratio < 0.78 && this.fps > this.config.targetFps + 5) {
        this.scale = clamp(this.scale + 0.02, this.config.minScale, this.config.maxScale, this.scale);
        this.config.drawDistance = Math.min(360, this.config.drawDistance + 6);
        this.config.maxActiveNpc = Math.min(80, this.config.maxActiveNpc + 1);
        this.config.maxActiveVehicles = Math.min(60, this.config.maxActiveVehicles + 1);
        this.config.maxParticles = Math.min(450, this.config.maxParticles + 15);
        this.applyRenderScale(this.scale);
      }
    }

    cullCollections(playerPos) {
      this.stats.culledObjects = 0;
      this.stats.culledNpc = 0;
      this.stats.culledVehicles = 0;

      const THREE = global.THREE;
      const useFrustum = Boolean(THREE && this._frustum && this._projScreenMatrix && this.camera);
      if (useFrustum) {
        this.camera.updateMatrixWorld();
        this._projScreenMatrix.multiplyMatrices(
          this.camera.projectionMatrix,
          this.camera.matrixWorldInverse
        );
        this._frustum.setFromProjectionMatrix(this._projScreenMatrix);
      }

      const maxDistSq = this.config.drawDistance * this.config.drawDistance;

      const processList = (list, maxActive, statKey) => {
        if (!Array.isArray(list)) return;
        let activeCount = 0;
        for (let i = 0; i < list.length; i++) {
          const item = list[i];
          const obj = item && (item.mesh || item.group || item.root || item);
          if (!obj || !obj.position) continue;

          let distSq = 0;
          if (playerPos) {
            const dx = obj.position.x - playerPos.x;
            const dy = obj.position.y - playerPos.y;
            const dz = obj.position.z - playerPos.z;
            distSq = dx * dx + dy * dy + dz * dz;
          }

          let inView = distSq <= maxDistSq;
          if (inView && useFrustum && obj.geometry && obj.geometry.boundingBox) {
            this._box.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld);
            inView = this._frustum.intersectsBox(this._box);
          }

          if (inView && activeCount < maxActive) {
            obj.visible = true;
            activeCount++;
          } else {
            obj.visible = false;
            this.stats[statKey]++;
            this.stats.culledObjects++;
          }
        }
      };

      processList(this.refs.npcs, this.config.maxActiveNpc, 'culledNpc');
      processList(this.refs.vehicles, this.config.maxActiveVehicles, 'culledVehicles');

      if (Array.isArray(this.refs.ragdollParts)) {
        let ragActive = 0;
        for (let i = 0; i < this.refs.ragdollParts.length; i++) {
          const part = this.refs.ragdollParts[i];
          if (!part) continue;
          const visible = ragActive < this.config.maxRagdollParts;
          part.visible = visible;
          if (visible) ragActive++;
        }
        this.stats.activeRagdoll = ragActive;
      }

      if (Array.isArray(this.refs.particles)) {
        let partActive = 0;
        for (let i = 0; i < this.refs.particles.length; i++) {
          const p = this.refs.particles[i];
          if (!p) continue;
          const visible = partActive < this.config.maxParticles;
          p.visible = visible;
          if (visible) partActive++;
        }
        this.stats.activeParticles = partActive;
      }
    }

    computeOfflinePreset() {
      const lowFps = this.fps < this.config.targetFps * 0.85;
      const highFps = this.fps > this.config.targetFps * 1.1;

      if (lowFps) {
        return {
          scale: clamp(this.scale - 0.08, this.config.minScale, this.config.maxScale, 0.75),
          drawDistance: Math.max(120, this.config.drawDistance - 25),
          cloudDensity: clamp(this.config.cloudDensity - 0.15, 0.2, 1.0, 0.5),
          exposure: clamp(this.config.exposure, 0.9, 1.3, 1.05),
          fogDensity: clamp(this.config.fogDensity * 1.1, 0.0005, 0.005, 0.0016),
          reason: 'Tryb offline: priorytet FPS przy obciążeniu sceny'
        };
      }

      if (highFps) {
        return {
          scale: clamp(this.scale + 0.05, this.config.minScale, this.config.maxScale, 1.0),
          drawDistance: Math.min(340, this.config.drawDistance + 20),
          cloudDensity: clamp(this.config.cloudDensity + 0.1, 0.2, 1.0, 0.85),
          exposure: clamp(this.config.exposure + 0.02, 0.95, 1.35, 1.12),
          fogDensity: clamp(this.config.fogDensity * 0.95, 0.0005, 0.005, 0.0012),
          reason: 'Tryb offline: zapas FPS — podbicie jakości obrazu'
        };
      }

      return {
        scale: this.scale,
        drawDistance: this.config.drawDistance,
        cloudDensity: this.config.cloudDensity,
        exposure: this.config.exposure,
        fogDensity: this.config.fogDensity,
        reason: 'Tryb offline: stabilny balans FPS i grafiki'
      };
    }

    applyTuningPatch(patch) {
      if (!patch || typeof patch !== 'object') return;
      if (patch.scale !== undefined) {
        this.applyRenderScale(patch.scale);
      }
      if (patch.drawDistance !== undefined) {
        this.config.drawDistance = clamp(patch.drawDistance, 100, 400, this.config.drawDistance);
      }
      if (patch.cloudDensity !== undefined) {
        this.config.cloudDensity = clamp(patch.cloudDensity, 0.1, 1.0, this.config.cloudDensity);
      }
      if (patch.exposure !== undefined) {
        this.config.exposure = clamp(patch.exposure, 0.75, 1.5, this.config.exposure);
      }
      if (patch.fogDensity !== undefined) {
        this.config.fogDensity = clamp(patch.fogDensity, 0.0003, 0.008, this.config.fogDensity);
      }
      if (typeof patch.reason === 'string' && patch.reason.trim()) {
        this.lastAiReason = patch.reason.trim().slice(0, 120);
      }
      this.applyGraphicsSettings();
    }

    async requestAiOptimization(force = false) {
      if (!this.config.aiEnabled && !force) return;
      if (this.aiBusy) return;

      const now = performance.now();
      if (!force && now - this.lastAiCall < this.config.aiIntervalMs) return;

      const telemetry = {
        fps: Math.round(this.fps),
        frameMs: Number(this.smoothFrameMs.toFixed(1)),
        targetFps: this.config.targetFps,
        scale: Number(this.scale.toFixed(2)),
        drawDistance: this.config.drawDistance,
        cloudDensity: Number(this.config.cloudDensity.toFixed(2)),
        exposure: Number(this.config.exposure.toFixed(2))
      };

      const cacheKey = `${hashState(telemetry)}_${Math.round(this.fps / 5)}`;
      if (this.cache.has(cacheKey)) {
        this.stats.cacheHits++;
        this.applyTuningPatch(this.cache.get(cacheKey));
        this.aiStatus = 'AI Cache (natychmiast)';
        this.updateOverlay();
        return;
      }

      if (typeof fetch !== 'function' || !this.apiKey) {
        const fallback = this.computeOfflinePreset();
        this.applyTuningPatch(fallback);
        this.aiStatus = 'Offline Fallback';
        this.updateOverlay();
        return;
      }

      this.aiBusy = true;
      this.lastAiCall = now;
      this.stats.aiCalls++;
      this.aiStatus = 'AI analizuje klatki...';
      this.updateOverlay();

      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      const timeoutId = controller ? setTimeout(() => controller.abort(), 4500) : null;

      try {
        const res = await fetch(GROQ_ENDPOINT, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.apiKey}`
          },
          signal: controller ? controller.signal : undefined,
          body: JSON.stringify({
            model: this.model,
            temperature: 0.2,
            max_tokens: 180,
            response_format: { type: 'json_object' },
            messages: [
              {
                role: 'system',
                content:
                  'You are a real-time 3D game graphics and FPS tuner. Return strictly JSON with keys: scale (0.55..1.0), drawDistance (110..360), cloudDensity (0.2..1.0), exposure (0.85..1.35), fogDensity (0.0005..0.004), reason (short Polish string).'
              },
              {
                role: 'user',
                content: `Telemetry: ${JSON.stringify(telemetry)}`
              }
            ]
          })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const rawContent =
          data &&
          data.choices &&
          data.choices[0] &&
          data.choices[0].message &&
          data.choices[0].message.content;

        const parsed = JSON.parse(rawContent);
        const safePatch = {
          scale: clamp(parsed.scale, this.config.minScale, this.config.maxScale, this.scale),
          drawDistance: clamp(parsed.drawDistance, 110, 360, this.config.drawDistance),
          cloudDensity: clamp(parsed.cloudDensity, 0.2, 1.0, this.config.cloudDensity),
          exposure: clamp(parsed.exposure, 0.85, 1.35, this.config.exposure),
          fogDensity: clamp(parsed.fogDensity, 0.0005, 0.004, this.config.fogDensity),
          reason: typeof parsed.reason === 'string' ? parsed.reason : 'Dostrojono przez AI'
        };

        this.cache.set(cacheKey, safePatch);
        if (this.cache.size > 40) {
          const firstKey = this.cache.keys().next().value;
          this.cache.delete(firstKey);
        }

        this.applyTuningPatch(safePatch);
        this.aiStatus = 'Groq AI Aktywne';
      } catch (_err) {
        const fallback = this.computeOfflinePreset();
        this.applyTuningPatch(fallback);
        this.aiStatus = 'AI Offline (Fallback)';
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        this.aiBusy = false;
        this.updateOverlay();
      }
    }

    update(nowMs = performance.now(), playerPos = null) {
      const dtMs = Math.max(1, Math.min(250, nowMs - this.lastFrameTime));
      this.lastFrameTime = nowMs;

      this.frameTimeMs = dtMs;
      this.smoothFrameMs = this.smoothFrameMs * 0.9 + dtMs * 0.1;
      this.fps = 1000 / this.smoothFrameMs;

      if (this.config.autoTune) {
        this.autoTuneByFrameTime(dtMs);
      }

      this.cullCollections(playerPos);

      if (this.config.aiEnabled && nowMs - this.lastAiCall >= this.config.aiIntervalMs) {
        this.requestAiOptimization(false);
      }

      if (this.config.showOverlay) {
        this.updateOverlay();
      }
    }

    boostFps() {
      this.applyRenderScale(Math.max(this.config.minScale, this.scale - 0.12));
      this.config.drawDistance = Math.max(120, this.config.drawDistance - 35);
      this.config.cloudDensity = Math.max(0.25, this.config.cloudDensity - 0.2);
      this.applyGraphicsSettings();
      this.lastAiReason = 'Wymuszono podbicie FPS';
      this.updateOverlay();
    }

    resetQuality() {
      this.config = Object.assign({}, this.config, {
        drawDistance: DEFAULT_CONFIG.drawDistance,
        maxActiveNpc: DEFAULT_CONFIG.maxActiveNpc,
        maxActiveVehicles: DEFAULT_CONFIG.maxActiveVehicles,
        maxRagdollParts: DEFAULT_CONFIG.maxRagdollParts,
        maxParticles: DEFAULT_CONFIG.maxParticles,
        cloudDensity: DEFAULT_CONFIG.cloudDensity,
        exposure: DEFAULT_CONFIG.exposure,
        fogDensity: DEFAULT_CONFIG.fogDensity
      });
      this.applyRenderScale(DEFAULT_CONFIG.maxScale);
      this.applyGraphicsSettings();
      this.lastAiReason = 'Przywrócono domyślne ustawienia grafiki';
      this.updateOverlay();
    }

    mountOverlay() {
      if (this._overlayEl || typeof document === 'undefined' || !document.body) return;

      const wrap = document.createElement('div');
      wrap.id = 'gta-sus-optimizer-hud';
      wrap.style.cssText = [
        'position:fixed',
        'right:12px',
        'bottom:12px',
        'z-index:9999',
        'background:rgba(12,15,24,0.82)',
        'color:#f1f5f9',
        'border:1px solid rgba(148,163,184,0.28)',
        'border-radius:10px',
        'padding:8px 10px',
        'font-family:monospace,sans-serif',
        'font-size:11px',
        'line-height:1.35',
        'backdrop-filter:blur(6px)',
        'min-width:210px',
        'user-select:none'
      ].join(';');

      const status = document.createElement('div');
      status.style.cssText = 'display:flex;justify-content:space-between;gap:8px;margin-bottom:4px;';

      const info = document.createElement('div');
      info.style.cssText = 'color:#94a3b8;font-size:10px;margin-bottom:6px;max-width:250px;';

      const btns = document.createElement('div');
      btns.style.cssText = 'display:flex;gap:5px;flex-wrap:wrap;';

      const makeBtn = (label, onClick) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = label;
        b.style.cssText = [
          'background:rgba(59,130,246,0.22)',
          'color:#e2e8f0',
          'border:1px solid rgba(96,165,250,0.45)',
          'border-radius:6px',
          'padding:2px 6px',
          'font-size:10px',
          'cursor:pointer'
        ].join(';');
        b.addEventListener('click', onClick);
        return b;
      };

      btns.appendChild(makeBtn('AI Tune', () => this.requestAiOptimization(true)));
      btns.appendChild(makeBtn('+FPS', () => this.boostFps()));
      btns.appendChild(makeBtn('Reset', () => this.resetQuality()));

      wrap.appendChild(status);
      wrap.appendChild(info);
      wrap.appendChild(btns);
      document.body.appendChild(wrap);

      this._overlayEl = wrap;
      this._statusEl = status;
      this._infoEl = info;
      this.updateOverlay();
    }

    updateOverlay() {
      if (!this._statusEl || !this._infoEl) return;
      const fpsVal = Math.round(this.fps);
      const scalePct = Math.round(this.scale * 100);
      this._statusEl.innerHTML =
        `<span><b>FPS: ${fpsVal}</b> (${this.smoothFrameMs.toFixed(1)}ms)</span>` +
        `<span>Res: ${scalePct}% | Cull: ${this.stats.culledObjects}</span>`;
      this._infoEl.textContent = `${this.aiStatus} • ${this.lastAiReason}`;
    }
  }

  const instance = new GtaSusOptimizer();
  global.GtaSusOptimizer = GtaSusOptimizer;
  global.GTA_SUS_OPTIMIZER = instance;
  global.optymalizer = instance;
})(typeof window !== 'undefined' ? window : globalThis);
