'use strict';

/**
 * @file 자율 이동 모듈 (ADHD) — idle 상태에서 캐릭터가 페이드아웃 후
 *       화면 내 랜덤 위치로 순간이동(블링크)하고 페이드인한다. 걷기/방향 없음.
 *       대화 중(작업 지시·능동 발화)·드래그·숨김 상태에선 멈춘다. 화면인식만 할 땐 계속.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.roam = (() => {
  const ROAM_MIN_MS = 5000;
  const ROAM_MAX_MS = 14000;
  const FADE_MS = 220;
  const EDGE_MARGIN = 8;
  const WIN_W = 400;
  const WIN_H = 700;

  let area = null;
  let moveTimer = null;
  let rafId = null;
  let dragging = false;
  let started = false;

  /**
   * [min, max) 범위 난수.
   * 
   * @param {number} min
   * @param {number} max
   * @returns {number}
   */
  function _rand(min, max) {
    return min + Math.random() * (max - min);
  }

  /**
   * 창이 캡처 화면 안에 완전히 들어오는 이동 범위 { minX, maxX, minY, maxY }.
   * 
   * @returns {Object}
   */
  function _range() {
    const b = area.bounds;
    return {
      minX: b.x + EDGE_MARGIN,
      maxX: b.x + b.width  - WIN_W - EDGE_MARGIN,
      minY: b.y + EDGE_MARGIN,
      maxY: b.y + b.height - WIN_H - EDGE_MARGIN,
    };
  }

  /**
   * 지금 이동해도 되는 상태인지 판정한다.
   * 대화(작업 지시=busy / 녹음 / 능동 발화=speaking)·드래그·숨김이면 멈춘다.
   * 
   * @returns {boolean}
   */
  function _canMove() {
    return started
      && !dragging
      && !Jarvis.state.get(Jarvis.KEYS.BUSY)
      && !Jarvis.state.get(Jarvis.KEYS.RECORDING)
      && !Jarvis.avatar.isSpeaking()
      && Jarvis.avatar.isVisible();
  }

  /**
   * 자율 이동을 시작한다. 화면 정보를 받아 첫 텔레포트를 예약한다.
   * 
   * @returns {Promise<void>}
   */
  async function start() {
    if (started) return;
    try {
      area = await window.electronAPI?.getScreenSize();
    } catch {
      area = null;
    }
    if (!area || !area.bounds) return;   // 화면 정보 못 얻으면 비활성
    started = true;
    _scheduleNext();
  }

  /**
   * 랜덤 간격 뒤 다음 텔레포트를 예약한다.
   * 
   * @returns {void}
   */
  function _scheduleNext() {
    if (moveTimer) clearTimeout(moveTimer);
    moveTimer = setTimeout(_maybeTeleport, _rand(ROAM_MIN_MS, ROAM_MAX_MS));
  }

  /**
   * 이동 가능하면 텔레포트하고, 다음 텔레포트를 예약한다.
   * 
   * @returns {Promise<void>}
   */
  async function _maybeTeleport() {
    if (_canMove()) {
      try { await _teleport(); } catch {}
    }
    _scheduleNext();
  }

  /**
   * 페이드아웃 → 화면 내 랜덤 위치로 창 이동 → 페이드인.
   * 
   * @returns {Promise<void>}
   */
  async function _teleport() {
    const r = _range();
    const tx = Math.round(_rand(r.minX, r.maxX));
    const ty = Math.round(_rand(r.minY, r.maxY));

    await _fade(1, 0);
    if (!_canMove()) { Jarvis.avatar.setModelAlpha(1); return; }
    window.electronAPI?.moveWindow(tx, ty);
    await _fade(0, 1);
    Jarvis.avatar.setModelAlpha(1);
  }

  /**
   * 모델 알파를 from→to 로 부드럽게 전환한다.
   * 
   * @param {number} from
   * @param {number} to
   * @returns {Promise<void>}
   */
  function _fade(from, to) {
    return new Promise((resolve) => {
      const startT = performance.now();
      const step = (now) => {
        if (!started) { rafId = null; resolve(); return; }   // 종료 시 중단
        const t = Math.min(1, (now - startT) / FADE_MS);
        Jarvis.avatar.setModelAlpha(from + (to - from) * t);
        if (t >= 1) { rafId = null; resolve(); return; }
        rafId = requestAnimationFrame(step);
      };
      rafId = requestAnimationFrame(step);
    });
  }

  // 드래그 중이면 텔레포트 정지
  Jarvis.bus.on(Jarvis.EVENTS.DRAG, (isDragging) => {
    dragging = isDragging;
  });

  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => {
    started = false;
    if (moveTimer) clearTimeout(moveTimer);
    moveTimer = null;
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    Jarvis.avatar.setModelAlpha(1);
  });

  return { start };
})();