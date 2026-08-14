(() => {
  'use strict';

  const SVG_SELECTOR = 'svg.design-network';
  const BASE_VIEWBOX = { x: 0, y: 0, width: 900, height: 390 };
  const MIN_ZOOM = 0.4;
  const MAX_ZOOM = 3;
  const BUTTON_ZOOM_STEP = 1.2;
  const states = new WeakMap();

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function copyBox(box) {
    return { x: box.x, y: box.y, width: box.width, height: box.height };
  }

  function boxString(box) {
    return `${box.x.toFixed(3)} ${box.y.toFixed(3)} ${box.width.toFixed(3)} ${box.height.toFixed(3)}`;
  }

  function zoomPercent(box) {
    return Math.round((BASE_VIEWBOX.width / box.width) * 100);
  }

  function getCanvasWrap(svg) {
    return svg.closest('.design-svg-wrap');
  }

  function clientPointToSvg(svg, clientX, clientY) {
    const matrix = svg.getScreenCTM?.();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = clientY;
    return point.matrixTransform(matrix.inverse());
  }

  function updateControls(state) {
    if (!state.controls?.isConnected) return;
    const percent = state.controls.querySelector('[data-camera-zoom-label]');
    if (percent) percent.textContent = `${zoomPercent(state.viewBox)}%`;
  }

  function applyViewBox(state) {
    if (!state.svg.isConnected) return;
    const next = boxString(state.viewBox);
    if (state.svg.getAttribute('viewBox') !== next) {
      state.svg.setAttribute('viewBox', next);
    }
    updateControls(state);
  }

  function setZoom(state, nextZoom, anchor = null) {
    const current = state.viewBox;
    const currentZoom = BASE_VIEWBOX.width / current.width;
    const zoom = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
    if (Math.abs(zoom - currentZoom) < 0.0001) return;

    const newWidth = BASE_VIEWBOX.width / zoom;
    const newHeight = BASE_VIEWBOX.height / zoom;
    const focus = anchor || {
      x: current.x + current.width / 2,
      y: current.y + current.height / 2,
    };

    const ratioX = current.width ? (focus.x - current.x) / current.width : 0.5;
    const ratioY = current.height ? (focus.y - current.y) / current.height : 0.5;

    state.viewBox = {
      x: focus.x - ratioX * newWidth,
      y: focus.y - ratioY * newHeight,
      width: newWidth,
      height: newHeight,
    };
    applyViewBox(state);
  }

  function resetView(state) {
    state.viewBox = copyBox(BASE_VIEWBOX);
    applyViewBox(state);
  }

  function fitView(state) {
    const svg = state.svg;
    const items = [...svg.querySelectorAll('.design-edge, .design-node')];
    let bounds = null;

    for (const item of items) {
      try {
        const box = item.getBBox();
        if (!Number.isFinite(box.x) || !Number.isFinite(box.y) || box.width <= 0 || box.height <= 0) continue;
        if (!bounds) {
          bounds = { x: box.x, y: box.y, x2: box.x + box.width, y2: box.y + box.height };
        } else {
          bounds.x = Math.min(bounds.x, box.x);
          bounds.y = Math.min(bounds.y, box.y);
          bounds.x2 = Math.max(bounds.x2, box.x + box.width);
          bounds.y2 = Math.max(bounds.y2, box.y + box.height);
        }
      } catch {
        // Ignore temporarily unavailable SVG geometry during React updates.
      }
    }

    if (!bounds) {
      resetView(state);
      return;
    }

    const padding = 42;
    let width = Math.max(170, bounds.x2 - bounds.x + padding * 2);
    let height = Math.max(92, bounds.y2 - bounds.y + padding * 2);
    const rect = svg.getBoundingClientRect();
    const aspect = rect.width > 0 && rect.height > 0 ? rect.width / rect.height : BASE_VIEWBOX.width / BASE_VIEWBOX.height;

    if (width / height > aspect) {
      height = width / aspect;
    } else {
      width = height * aspect;
    }

    const fittedZoom = clamp(BASE_VIEWBOX.width / width, MIN_ZOOM, 1.75);
    width = BASE_VIEWBOX.width / fittedZoom;
    height = BASE_VIEWBOX.height / fittedZoom;

    const centerX = (bounds.x + bounds.x2) / 2;
    const centerY = (bounds.y + bounds.y2) / 2;
    state.viewBox = {
      x: centerX - width / 2,
      y: centerY - height / 2,
      width,
      height,
    };
    applyViewBox(state);
  }

  function createButton(label, title, className = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `interfy-camera-button ${className}`.trim();
    button.textContent = label;
    button.title = title;
    button.setAttribute('aria-label', title);
    return button;
  }

  function createControls(state) {
    const wrap = getCanvasWrap(state.svg);
    if (!wrap) return null;

    const existing = wrap.querySelector(':scope > .interfy-diagram-camera');
    if (existing) {
      state.controls = existing;
      updateControls(state);
      return existing;
    }

    const controls = document.createElement('div');
    controls.className = 'interfy-diagram-camera';
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', '다이어그램 확대 축소 및 이동');

    const zoomOut = createButton('−', '축소');
    const zoomLabel = document.createElement('span');
    zoomLabel.className = 'interfy-camera-zoom-label';
    zoomLabel.dataset.cameraZoomLabel = '';
    const zoomIn = createButton('+', '확대');
    const fit = createButton('맞춤', '전체 노드를 화면에 맞춤', 'interfy-camera-text-button');
    const reset = createButton('1:1', '기본 보기로 초기화', 'interfy-camera-text-button');

    zoomOut.addEventListener('click', event => {
      event.stopPropagation();
      setZoom(state, (BASE_VIEWBOX.width / state.viewBox.width) / BUTTON_ZOOM_STEP);
    });
    zoomIn.addEventListener('click', event => {
      event.stopPropagation();
      setZoom(state, (BASE_VIEWBOX.width / state.viewBox.width) * BUTTON_ZOOM_STEP);
    });
    fit.addEventListener('click', event => {
      event.stopPropagation();
      fitView(state);
    });
    reset.addEventListener('click', event => {
      event.stopPropagation();
      resetView(state);
    });

    controls.append(zoomOut, zoomLabel, zoomIn, fit, reset);
    wrap.appendChild(controls);
    state.controls = controls;
    updateControls(state);
    return controls;
  }

  function ensureControls(state) {
    if (!state.controls?.isConnected) createControls(state);
  }

  function attach(svg) {
    if (states.has(svg)) {
      ensureControls(states.get(svg));
      return;
    }

    const state = {
      svg,
      viewBox: copyBox(BASE_VIEWBOX),
      controls: null,
      dragging: null,
    };
    states.set(svg, state);
    svg.classList.add('interfy-camera-ready');
    createControls(state);
    applyViewBox(state);

    svg.addEventListener('wheel', event => {
      event.preventDefault();
      const anchor = clientPointToSvg(svg, event.clientX, event.clientY);
      if (!anchor) return;
      const currentZoom = BASE_VIEWBOX.width / state.viewBox.width;
      const factor = Math.exp(-event.deltaY * 0.0012);
      setZoom(state, currentZoom * factor, anchor);
    }, { passive: false });

    svg.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target !== svg) return;
      event.preventDefault();
      state.dragging = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startBox: copyBox(state.viewBox),
      };
      svg.setPointerCapture?.(event.pointerId);
      svg.classList.add('interfy-camera-panning');
    });

    svg.addEventListener('pointermove', event => {
      const drag = state.dragging;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const rect = svg.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      const dxPixels = event.clientX - drag.startX;
      const dyPixels = event.clientY - drag.startY;

      state.viewBox = {
        ...drag.startBox,
        x: drag.startBox.x - dxPixels * drag.startBox.width / rect.width,
        y: drag.startBox.y - dyPixels * drag.startBox.height / rect.height,
      };
      applyViewBox(state);
    });

    const finishPan = event => {
      const drag = state.dragging;
      if (!drag || drag.pointerId !== event.pointerId) return;
      state.dragging = null;
      svg.releasePointerCapture?.(event.pointerId);
      svg.classList.remove('interfy-camera-panning');
    };
    svg.addEventListener('pointerup', finishPan);
    svg.addEventListener('pointercancel', finishPan);

    const attributeObserver = new MutationObserver(() => {
      if (!svg.isConnected) return;
      const expected = boxString(state.viewBox);
      if (svg.getAttribute('viewBox') !== expected) {
        requestAnimationFrame(() => applyViewBox(state));
      }
    });
    attributeObserver.observe(svg, { attributes: true, attributeFilter: ['viewBox'] });
  }

  function scan() {
    document.querySelectorAll('.interfy-diagram-camera').forEach(controls => {
      if (!controls.parentElement?.querySelector(SVG_SELECTOR)) controls.remove();
    });
    document.querySelectorAll(SVG_SELECTOR).forEach(attach);
    document.querySelectorAll(SVG_SELECTOR).forEach(svg => {
      const state = states.get(svg);
      if (state) ensureControls(state);
    });
  }

  let scanQueued = false;
  function queueScan() {
    if (scanQueued) return;
    scanQueued = true;
    requestAnimationFrame(() => {
      scanQueued = false;
      scan();
    });
  }

  const observer = new MutationObserver(queueScan);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', queueScan, { once: true });
  } else {
    queueScan();
  }
})();
