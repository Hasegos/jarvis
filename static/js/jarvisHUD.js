/**
 * J.A.R.V.I.S  ARC HUD
 */
(function () {
  'use strict';

  /**
   *  1. 상수
   */
  const SIZE = 200;

  // BEM 클래스명 상수
  const CSS = Object.freeze({
    STATUS        : 'hud__status',
    STATUS_IDLE   : 'hud__status--idle',
    STATUS_THINK  : 'hud__status--thinking',
    STATUS_SPEAK  : 'hud__status--speaking',
    WAVE          : 'thinking-wave',
    WAVE_ACTIVE   : 'thinking-wave--active',
    MSG_USER      : 'chat-messages__item--user',
    MSG_ASSISTANT : 'chat-messages__item--assistant',
  });

  // 색 팔레트
  const P  = [79,  195, 247];
  const AC = [245, 158, 11 ];
  const W  = [255, 255, 255];
  const ca = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;

  // 상태별 파라미터
  const SP = {
    idle    : { spd: 1.0, glow: 0.45, act: 0.15 },
    thinking: { spd: 2.4, glow: 0.88, act: 0.65 },
    speaking: { spd: 4.0, glow: 1.20, act: 1.00 },
  };

  // 상태 레이블 맵
  const STATE_LABEL = {
    idle     : '● STANDBY',
    thinking : '◈ PROCESSING...',
    speaking : '◉ ACTIVE',
  };

  /**
   * 2. 런타임 상태
   */
  let ctx      = null;
  let t        = 0;
  let hudState = 'idle';

  /**
   * 3. Canvas 초기화 (Retina 대응)
   * 
   * @returns 
   */
  function initCtx() {
    const cv = document.getElementById('jarvisHUD');
    if (!cv) return false;
    const dpr   = Math.min(window.devicePixelRatio || 1, 2);
    cv.width    = SIZE * dpr;
    cv.height   = SIZE * dpr;
    cv.style.width  = SIZE + 'px';
    cv.style.height = SIZE + 'px';
    ctx = cv.getContext('2d');
    ctx.scale(dpr, dpr);
    return true;
  }

  /**
   * 4. 프레임 렌더
   * 
   * @returns 
   */
  function draw() {
    if (!ctx) return;
    const S  = SIZE, cx = S/2, cy = S/2;
    const sp = SP[hudState] || SP.idle;
    const R  = S * 0.43;

    ctx.clearRect(0, 0, S, S);

    // 배경 방사형 글로우
    const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.15);
    bg.addColorStop(0,   ca(P, 0.08 * sp.glow));
    bg.addColorStop(0.7, ca(P, 0.02 * sp.glow));
    bg.addColorStop(1,   'rgba(0,0,0,0)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, S, S);

    // 외부 기준 링
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI*2);
    ctx.strokeStyle = ca(P, 0.28);
    ctx.lineWidth   = 1.5;
    ctx.stroke();

    // 외부 후광 밴드
    ctx.beginPath();
    ctx.arc(cx, cy, R + 6, 0, Math.PI*2);
    ctx.strokeStyle = ca(P, 0.10);
    ctx.lineWidth   = 10;
    ctx.stroke();

    // 틱마크 (천천히 회전)
    const tickOff = t * sp.spd * 0.16;
    for (let i = 0; i < 90; i++) {
      const ang = (i/90)*Math.PI*2 + tickOff;
      const co  = Math.cos(ang), si = Math.sin(ang);
      const isL = i % 15 === 0;
      const isM = i %  5 === 0;
      const len = isL ? 16 : (isM ? 9 : 4);
      const opa = isL ? 1.0 : (isM ? 0.55 : 0.22);
      ctx.beginPath();
      ctx.moveTo(cx + co*(R-len), cy + si*(R-len));
      ctx.lineTo(cx + co*R,       cy + si*R);
      ctx.strokeStyle = ca(P, opa);
      ctx.lineWidth   = isL ? 2.5 : 1;
      ctx.stroke();
    }

    // 앰버 액센트 아크 (정회전)
    const aAng = t * sp.spd * 0.5 - Math.PI/2;
    const aLen = 0.38 + Math.sin(t*1.4)*0.12*sp.act;
    ctx.beginPath();
    ctx.arc(cx, cy, R - 7, aAng, aAng + aLen);
    ctx.strokeStyle  = ca(AC, 0.95 * sp.glow);
    ctx.lineWidth    = 6;
    ctx.shadowColor  = ca(AC, 0.8);
    ctx.shadowBlur   = 12;
    ctx.stroke();
    ctx.shadowBlur   = 0;

    ctx.beginPath();
    ctx.arc(cx, cy, R - 7, aAng+Math.PI+0.6, aAng+Math.PI+1.0);
    ctx.strokeStyle = ca(AC, 0.55 * sp.glow);
    ctx.lineWidth   = 3;
    ctx.stroke();

    // 시안 진행 아크 (역회전)
    const cAng = -(t * sp.spd * 0.26) + Math.PI*0.6;
    const cLen = (0.5 + sp.act * 0.55) * Math.PI;
    ctx.beginPath();
    ctx.arc(cx, cy, R - 16, cAng, cAng + cLen);
    ctx.strokeStyle = ca(P, 0.75 * sp.glow);
    ctx.lineWidth   = 3;
    ctx.shadowColor = ca(P, 0.5);
    ctx.shadowBlur  = 8;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // 세그먼트 링 (역회전, 상태에 따라 점등)
    const segR   = R * 0.73;
    const segOff = -(t * sp.spd * 0.5);
    const NSEG   = 36;
    for (let i = 0; i < NSEG; i++) {
      const a1  = (i/NSEG)*Math.PI*2 + segOff;
      const a2  = a1 + (Math.PI*2/NSEG) * 0.6;
      const lit = Math.sin(t*2.8 + i*0.9) > (1.1 - sp.act*2.0);
      ctx.beginPath();
      ctx.arc(cx, cy, segR, a1, a2);
      ctx.strokeStyle = ca(P, lit ? 0.88*sp.glow : 0.10);
      ctx.lineWidth   = 4.5;
      ctx.stroke();
    }

    // 내부 디테일 링 (정회전)
    const inR   = R * 0.57;
    const inOff = t * sp.spd * 1.3;
    ctx.beginPath();
    ctx.arc(cx, cy, inR, 0, Math.PI*2);
    ctx.strokeStyle = ca(P, 0.15);
    ctx.lineWidth   = 1;
    ctx.stroke();

    const nArcs = hudState==='speaking' ? 8 : hudState==='thinking' ? 5 : 3;
    for (let i = 0; i < nArcs; i++) {
      const a = (i/nArcs)*Math.PI*2 + inOff;
      ctx.beginPath();
      ctx.arc(cx, cy, inR, a, a+0.30);
      ctx.strokeStyle = ca(AC, 0.72*sp.glow);
      ctx.lineWidth   = 3;
      ctx.stroke();
    }

    // 4방향 카디널 마커
    [0, Math.PI/2, Math.PI, Math.PI*1.5].forEach(ang => {
      const mr = R * 1.07;
      const px = cx + Math.cos(ang)*mr, py = cy + Math.sin(ang)*mr;
      ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI*2);
      ctx.fillStyle = ca(AC, 0.95); ctx.fill();
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI*2);
      ctx.strokeStyle = ca(AC, 0.3); ctx.lineWidth = 1; ctx.stroke();
      const cl = 7;
      ctx.strokeStyle = ca(AC, 0.5); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(px-cl, py); ctx.lineTo(px+cl, py); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px, py-cl); ctx.lineTo(px, py+cl); ctx.stroke();
    });

    // 코어 글로우
    const cR  = R * 0.28;
    const pul = 1 + Math.sin(t*(hudState==='speaking' ? 5.5 : hudState==='thinking' ? 3.2 : 1.6))*0.07;
    const cg  = ctx.createRadialGradient(cx,cy,0, cx,cy, cR*3*pul);
    cg.addColorStop(0,   ca(W, 0.18*sp.glow));
    cg.addColorStop(0.3, ca(P, 0.28*sp.glow));
    cg.addColorStop(1,   'rgba(0,0,0,0)');
    ctx.fillStyle = cg;
    ctx.beginPath(); ctx.arc(cx, cy, cR*3*pul, 0, Math.PI*2); ctx.fill();

    ctx.beginPath(); ctx.arc(cx, cy, cR*pul, 0, Math.PI*2);
    ctx.strokeStyle = ca(P, 0.7*sp.glow);
    ctx.lineWidth   = 2;
    ctx.shadowColor = ca(P, sp.glow);
    ctx.shadowBlur  = cR*0.5;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // 텍스트
    ctx.save();
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';

    ctx.font        = `900 ${S*0.08}px 'Orbitron', sans-serif`;
    ctx.fillStyle   = ca(P, 0.95);
    ctx.shadowColor = ca(P, 0.9);
    ctx.shadowBlur  = 14;
    ctx.fillText('J.A.R.V.I.S', cx, cy - S*0.018);

    ctx.shadowBlur = 0;
    ctx.font       = `${S*0.05}px 'Share Tech Mono', monospace`;
    const stMap    = { idle:'STANDBY', thinking:'PROCESSING', speaking:'ACTIVE' };
    ctx.fillStyle  = hudState==='idle' ? ca(P,0.45) : ca(AC, 0.92);
    ctx.fillText(stMap[hudState]||'STANDBY', cx, cy + S*0.075);
    ctx.restore();
  }

  /**
   * rAF 루프 — 매 프레임 t를 증가시키고 draw를 호출합니다.
   */
  function tick() { 
    t += 0.016; draw();
    requestAnimationFrame(tick); 
  }

  /**
   * 5. 상태 변경
   * HUD 애니메이션 상태, 상태 텍스트, 파동 UI를 동시에 갱신합니다.
   * 
   * @param {'idle'|'thinking'|'speaking'} ns - 새 상태
   */
  function setState(ns) {
    hudState = ns;

    // HUD 상태 텍스트 (BEM 클래스)
    const el = document.getElementById('hudStatus');
    if (el) {
      el.textContent = STATE_LABEL[ns] || STATE_LABEL.idle;
      el.className   = `${CSS.STATUS} ${CSS['STATUS_' + ns.toUpperCase()] || CSS.STATUS_IDLE}`;
    }

    // 생각중 파동
    const wave = document.getElementById('thinkingWave');
    if (wave) {
      wave.classList.toggle(CSS.WAVE_ACTIVE, ns === 'thinking');
    }
  }


  /**
   * 6. MutationObserver — 채팅 메시지 변화 감지
   * 
   * @returns 
   */
  function initObserver() {
    const box = document.getElementById('chatBox');
    if (!box) { setTimeout(initObserver, 300); return; }

    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(node => {
        if (!node.classList) return;
        if (node.classList.contains(CSS.MSG_USER)) {
          setState('thinking');
        }
        if (node.classList.contains(CSS.MSG_ASSISTANT)) {
          setState('speaking');
          const dur = Math.min(Math.max((node.textContent||'').length * 35, 2500), 9000);
          setTimeout(() => { if (hudState === 'speaking') setState('idle'); }, dur);
        }
      }));
    }).observe(box, { childList: true });
  }

  /**
   * 7. 초기화
   * 
   * @returns 
   */
  function init() {
    if (!initCtx()) return;
    initObserver();
    tick();
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  
  window.JarvisHUD = { setState };
})();