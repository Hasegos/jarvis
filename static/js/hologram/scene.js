/**
 * JARVIS 홀로그램 — Three.js 씬
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  /**
   * 색상 팔레트
   */
  const COLORS = {
    gold:       new THREE.Color(0xffb24d),
    goldBright: new THREE.Color(0xffe0aa),
    blue:       new THREE.Color(0x4db4ff),
    green:      new THREE.Color(0x4dff9e),
    orange:     new THREE.Color(0xff8a3d),
    white:      new THREE.Color(0xffffff),
  };

  /**
   * 도구별 색상 매핑
   *
   * web_search=파랑, vault_write=초록, file_ops=주황.
   */
  const TOOL_COLORS = { web: COLORS.blue, vault: COLORS.green, file: COLORS.orange };
  const TOOL_COLOR_BY_NAME = {
    web_search: COLORS.blue, vault_write: COLORS.green, file_ops: COLORS.orange,
  };

  /**
   * 구체 상태별 목표 파라미터
   *
   * idle: 부드러운 금색 회전.
   * recording: 코어 밝아짐 + 반경 호흡(심장박동).
   * tts: 맥박 팽창/수축 (규칙적 호흡).
   * tool: 도구별 색 전환 + 활발한 움직임.
   */
  const STATE = {
    idle:      { radius: 1.00, wave: 0.05, swirl: 0.10, core: 1.00, beam: 1.00, bloom: 0.50,
                pulseAmp: 0.08, pulseSpeed: 1.6, excursion: 1.00, breathe: 0.03, color: COLORS.gold,       tool: 0, label: '' },
    recording: { radius: 1.05, wave: 0.04, swirl: 0.10, core: 1.70, beam: 1.40, bloom: 0.85,
                pulseAmp: 0.30, pulseSpeed: 2.0, excursion: 0.18, breathe: 0.32, color: COLORS.goldBright, tool: 0, label: '듣고 있습니다…' },
    tts:       { radius: 1.03, wave: 0.04, swirl: 0.10, core: 1.65, beam: 1.35, bloom: 0.82,
                pulseAmp: 0.34, pulseSpeed: 2.4, excursion: 0.18, breathe: 0.36, color: COLORS.gold,       tool: 0, label: '응답 중…' },
    tool:      { radius: 1.08, wave: 0.10, swirl: 0.20, core: 1.45, beam: 1.25, bloom: 0.78,
                pulseAmp: 0.16, pulseSpeed: 3.0, excursion: 0.55, breathe: 0.16, color: COLORS.blue,       tool: 1, label: '' },
  };

  /**
   * 현재 보간 중인 파라미터 (매 프레임 lerp)
   */
  const cur = {
    radius: 1, wave: 0.05, swirl: 0.10, core: 1, beam: 1, bloom: 0.5,
    pulseAmp: 0.08, pulseSpeed: 1.6, excursion: 1, breathe: 0.02, tool: 0,
    color: COLORS.gold.clone(),
  };

  /** 매 프레임 재할당 방지용 스크래치 컬러 (GC 부담 감소) */
  const _beamTint = new THREE.Color();

  /**
   * 파티클 vertex shader
   *
   * 파티클별 속성(방향/회전/진폭/속도/위상)을 attribute로 받아
   * GPU에서 위치를 계산한다. JS는 uniform(시간/상태)만 갱신.
   */
  const PARTICLE_VS = `
    attribute vec3 aDir;
    attribute float aSwirl;
    attribute float aRadAmp;
    attribute float aRadSpd;
    attribute float aPhase;
    uniform float uTime, uRadius, uWave, uSwirl, uExcursion, uBreathe, uBoot, uSize, uScale;
    void main() {
      float a = uTime * aSwirl * uSwirl * 4.0;
      float ca = cos(a), sa = sin(a);
      vec3 d = vec3(aDir.x * ca - aDir.z * sa, aDir.y, aDir.x * sa + aDir.z * ca);
      float wob = uWave * sin(uTime * 3.0 + aPhase)
                + aRadAmp * uExcursion * sin(uTime * aRadSpd + aPhase);
      float breathe = uBreathe * sin(uTime * 2.0);
      vec3 spherePos = d * (uRadius + breathe + wob);
      vec3 pos = mix(position, spherePos, uBoot);
      vec4 mv = modelViewMatrix * vec4(pos, 1.0);
      gl_PointSize = max(1.0, uSize * uScale / -mv.z);
      gl_Position = projectionMatrix * mv;
    }
  `;

  /**
   * 파티클 fragment shader
   *
   * 글로우 텍스처를 적용하고 투명 부분을 discard한다.
   */
  const PARTICLE_FS = `
    uniform vec3 uColor;
    uniform sampler2D uTex;
    void main() {
      vec4 tex = texture2D(uTex, gl_PointCoord);
      if (tex.a < 0.01) discard;
      gl_FragColor = vec4(uColor, 1.0) * tex;
    }
  `;

  // 모듈 로컬 Three.js 객체
  let scene, camera, renderer, composer, bloomPass, controls, clock;
  let particleUniforms, core, beamGroup, beams = [], rings = [], stars;
  let lastFrame = 0;

  /**
   * 피보나치 구면 분포
   *
   * n개의 점을 단위 구면에 균일하게 배치한다.
   *
   * @param {number} n - 생성할 점 개수
   * @returns {THREE.Vector3[]} 단위 구면 위 방향 벡터 배열
   */
  function fibSphere(n) {
    const out = [];
    const phi = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const t = phi * i;
      out.push(new THREE.Vector3(Math.cos(t) * r, y, Math.sin(t) * r));
    }
    return out;
  }

  /**
   * 균일 분포 랜덤 방향
   *
   * Three.js r128에는 Vector3.randomDirection이 없어 직접 계산한다.
   *
   * @returns {THREE.Vector3} 단위 구면 위 랜덤 방향 벡터
   */
  function randomDir() {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const s = Math.sin(phi);
    return new THREE.Vector3(s * Math.cos(theta), s * Math.sin(theta), Math.cos(phi));
  }

  /**
   * 코어/파티클 글로우 텍스처 생성
   *
   * Canvas API로 방사형 그라데이션 텍스처(128x128)를 만든다.
   *
   * @returns {THREE.CanvasTexture} 발광 효과용 텍스처
   */
  function makeGlowTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0,   'rgba(255,255,255,1)');
    g.addColorStop(0.2, 'rgba(255,228,170,0.95)');
    g.addColorStop(0.5, 'rgba(255,178,77,0.4)');
    g.addColorStop(1,   'rgba(255,178,77,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  /**
   * 포인트 크기 보정 스케일
   *
   * fov와 뷰포트 높이 기반으로 파티클 크기를 보정한다.
   * initScene 완료 후 및 리사이즈 시 갱신.
   *
   * @returns {number} 보정 스케일 값
   */
  function pointScale() {
    const fov = camera.fov * Math.PI / 180;
    return (innerHeight * renderer.getPixelRatio()) / (2 * Math.tan(fov / 2));
  }

  /**
   * ease-in-out 보간
   *
   * 부팅 파티클 수렴 애니메이션에 사용한다.
   *
   * @param {number} x - 0~1 진행도
   * @returns {number} 보간된 값 (0~1)
   */
  function easeInOut(x) {
    return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
  }

  /**
   * 1. 씬 구성
   *
   * 파티클 구체, 코어, 빔, 링, 별, Bloom, OrbitControls를 생성하고
   * 렌더 루프를 시작한다.
   */
  J.initScene = function () {
    const C = J.const;
    const canvas = document.getElementById('orbCanvas');
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 200);
    camera.position.set(0, 0, 8);

    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true });
    renderer.setSize(innerWidth, innerHeight);
    renderer.setPixelRatio(1.0);

    const glow = makeGlowTexture();

    // ── 파티클 구체 ──
    const dirs = fibSphere(C.PARTICLE_COUNT);
    const basePos = new Float32Array(C.PARTICLE_COUNT * 3);
    const aDir    = new Float32Array(C.PARTICLE_COUNT * 3);
    const aSwirl  = new Float32Array(C.PARTICLE_COUNT);
    const aRadAmp = new Float32Array(C.PARTICLE_COUNT);
    const aRadSpd = new Float32Array(C.PARTICLE_COUNT);
    const aPhase  = new Float32Array(C.PARTICLE_COUNT);
    for (let i = 0; i < C.PARTICLE_COUNT; i++) {
      const d = dirs[i], s = 7 + Math.random() * 7;
      basePos[i * 3]     = d.x * s + (Math.random() - 0.5) * 4;
      basePos[i * 3 + 1] = d.y * s + (Math.random() - 0.5) * 4;
      basePos[i * 3 + 2] = d.z * s + (Math.random() - 0.5) * 4;
      aDir[i * 3] = d.x; aDir[i * 3 + 1] = d.y; aDir[i * 3 + 2] = d.z;
      aSwirl[i]  = (0.2 + Math.random() * 0.8) * (Math.random() < 0.5 ? 1 : -1);
      aRadAmp[i] = Math.random() < 0.1 ? 0.6 + Math.random() * 0.9 : Math.random() * 0.12;
      aRadSpd[i] = 0.5 + Math.random() * 1.5;
      aPhase[i]  = Math.random() * Math.PI * 2;
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(basePos, 3));
    geom.setAttribute('aDir',    new THREE.BufferAttribute(aDir, 3));
    geom.setAttribute('aSwirl',  new THREE.BufferAttribute(aSwirl, 1));
    geom.setAttribute('aRadAmp', new THREE.BufferAttribute(aRadAmp, 1));
    geom.setAttribute('aRadSpd', new THREE.BufferAttribute(aRadSpd, 1));
    geom.setAttribute('aPhase',  new THREE.BufferAttribute(aPhase, 1));

    particleUniforms = {
      uTime:      { value: 0 },
      uRadius:    { value: C.SPHERE_R },
      uWave:      { value: 0.05 },
      uSwirl:     { value: 0.10 },
      uExcursion: { value: 1.0 },
      uBreathe:   { value: 0.02 },
      uBoot:      { value: 0 },
      uSize:      { value: 0.09 },
      uScale:     { value: 1 },
      uColor:     { value: cur.color },
      uTex:       { value: glow },
    };
    const points = new THREE.Points(geom, new THREE.ShaderMaterial({
      uniforms: particleUniforms,
      vertexShader: PARTICLE_VS,
      fragmentShader: PARTICLE_FS,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    points.frustumCulled = false;
    scene.add(points);

    // ── 중앙 코어 ──
    core = new THREE.Sprite(new THREE.SpriteMaterial({
      map: glow, color: 0xffffff, transparent: true, opacity: 0.9,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    core.scale.setScalar(1.5);
    scene.add(core);

    // ── 방사형 빛줄기 ──
    beamGroup = new THREE.Group();
    for (let i = 0; i < C.BEAM_COUNT; i++) {
      const d = randomDir();
      const len = C.SPHERE_R * (1.1 + Math.random() * 0.9);
      const g = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0), d.clone().multiplyScalar(len),
      ]);
      g.setAttribute('color', new THREE.BufferAttribute(new Float32Array([
        1.0, 0.85, 0.45, 1.0, 0.5, 0.15,
      ]), 3));
      const line = new THREE.Line(g, new THREE.LineBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      line.userData = { phase: Math.random() * Math.PI * 2, speed: 1 + Math.random() * 2 };
      beams.push(line);
      beamGroup.add(line);
    }
    scene.add(beamGroup);

    // ── 궤도 링 ──
    [
      { r: 3.6, tilt: [Math.PI / 2.2, 0, 0] },
      { r: 4.3, tilt: [Math.PI / 1.7, 0, Math.PI / 5] },
      { r: 5.0, tilt: [Math.PI / 2.5, Math.PI / 6, 0] },
    ].forEach(d => {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(d.r, d.r + 0.06, 128),
        new THREE.MeshBasicMaterial({
          color: COLORS.gold, transparent: true, opacity: 0.30,
          side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false,
        }),
      );
      ring.rotation.set(...d.tilt);
      rings.push(ring);
      scene.add(ring);
    });

    // ── 별 배경 ──
    const starPos = new Float32Array(C.STAR_COUNT * 3);
    for (let i = 0; i < C.STAR_COUNT; i++) {
      const d = randomDir().multiplyScalar(40 + Math.random() * 50);
      starPos[i * 3] = d.x; starPos[i * 3 + 1] = d.y; starPos[i * 3 + 2] = d.z;
    }
    const starGeom = new THREE.BufferGeometry();
    starGeom.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    stars = new THREE.Points(starGeom, new THREE.PointsMaterial({
      color: 0x99aacc, size: 0.18, transparent: true, opacity: 0.7, depthWrite: false,
    }));
    scene.add(stars);

    // ── 후처리 ──
    composer = new THREE.EffectComposer(renderer);
    composer.addPass(new THREE.RenderPass(scene, camera));
    bloomPass = new THREE.UnrealBloomPass(
      new THREE.Vector2(innerWidth * 0.5, innerHeight * 0.5), 0.5, 0.4, 0.35);
    composer.addPass(bloomPass);

    // ── 카메라 컨트롤 ─
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = 4;
    controls.maxDistance = 18;
    controls.rotateSpeed = 0.6;

    particleUniforms.uScale.value = pointScale();
    clock = new THREE.Clock();
    addEventListener('resize', onResize);
    requestAnimationFrame(animate);
  };

  /**
   * 윈도우 리사이즈 핸들러
   *
   * 카메라 비율, 렌더러 크기, Bloom 해상도, 파티클 스케일을 갱신한다.
   */
  function onResize() {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    composer.setSize(innerWidth, innerHeight);
    bloomPass.setSize(innerWidth * 0.5, innerHeight * 0.5);
    particleUniforms.uScale.value = pointScale();
  }

  /**
   * 2. 렌더 루프 (30fps 캡)
   *
   * 상태 보간 → 파티클/코어/빔/링/별 갱신 → Bloom → 렌더.
   * 탭 비활성 시 렌더를 건너뛴다.
   *
   * @param {number} ts - requestAnimationFrame 타임스탬프 (ms)
   */
  function animate(ts) {
    requestAnimationFrame(animate);
    if (document.hidden) return;
    if (ts - lastFrame < J.const.FRAME_MS) return;
    lastFrame = ts;

    const dt = Math.min(clock.getDelta(), 0.05);
    const t = clock.getElapsedTime();
    const s = STATE[J.state.sphereState];
    const k = Math.min(1, dt * 4);

    // 상태 보간
    cur.radius += (s.radius - cur.radius) * k;
    cur.wave   += (s.wave - cur.wave) * k;
    cur.swirl  += (s.swirl - cur.swirl) * k;
    cur.core   += (s.core - cur.core) * k;
    cur.beam   += (s.beam - cur.beam) * k;
    cur.bloom  += (s.bloom - cur.bloom) * k;
    cur.pulseAmp += (s.pulseAmp - cur.pulseAmp) * k;
    cur.pulseSpeed += (s.pulseSpeed - cur.pulseSpeed) * k;
    cur.excursion += (s.excursion - cur.excursion) * k;
    cur.breathe += (s.breathe - cur.breathe) * k;
    cur.tool   += (s.tool - cur.tool) * k;

    // 도구 상태면 도구별 색, 아니면 상태 기본색
    let targetColor = s.color;
    if (J.state.sphereState === 'tool' && J.state.toolColor) targetColor = J.state.toolColor;
    cur.color.lerp(targetColor, k);

    const breathe = cur.breathe * Math.sin(t * 2);
    const pulse = 1 + cur.pulseAmp * Math.sin(t * cur.pulseSpeed);

    // 파티클
    particleUniforms.uTime.value      = t;
    particleUniforms.uRadius.value    = J.const.SPHERE_R * cur.radius;
    particleUniforms.uWave.value      = cur.wave;
    particleUniforms.uSwirl.value     = cur.swirl;
    particleUniforms.uExcursion.value = cur.excursion;
    particleUniforms.uBreathe.value   = cur.breathe;
    particleUniforms.uBoot.value      = J.three.booting ? easeInOut(J.three.bootProgress) : 1;

    // 코어 — 맥박 밝기/크기
    core.scale.setScalar(1.5 * cur.core * pulse);

    // 빔 — 호흡 + 개별 깜빡임 + 회전 + 색 전환
    beamGroup.scale.setScalar(cur.beam + breathe * 0.8);
    beamGroup.rotation.y += dt * 0.15 * (0.5 + cur.swirl);
    beamGroup.rotation.x += dt * 0.05;
    _beamTint.copy(COLORS.white).lerp(cur.color, cur.tool * 0.8);
    beams.forEach(b => {
      const u = b.userData;
      b.material.opacity = 0.45 + 0.40 * Math.abs(Math.sin(t * u.speed + u.phase));
      b.material.color.copy(_beamTint);
    });

    // 링
    rings.forEach((r, i) => {
      r.rotation.z += dt * (0.2 + i * 0.12) * (0.5 + cur.swirl);
      r.material.color.copy(cur.color);
    });

    // 별
    stars.rotation.y += dt * 0.01;

    bloomPass.strength += (cur.bloom - bloomPass.strength) * k;
    controls.update();
    composer.render();
  }

  /**
   * 구체 상태 전환
   *
   * 상태를 변경하고 하단 라벨을 갱신한다.
   *
   * @param {string} state - 전환할 상태 ('idle' | 'recording' | 'tts' | 'tool')
   * @param {string|null} label - 라벨 텍스트 (null이면 상태 기본 라벨 사용)
   */
  J.setSphereState = function (state, label) {
    J.state.sphereState = state;
    const text = label != null ? label : STATE[state].label;
    J.dom.orbState.textContent = text;
    J.dom.orbState.classList.toggle('orb-state--on', !!text);
  };

  /**
   * 도구 색상 설정
   *
   * 도구명을 우선 매핑하고, 없으면 상태 문구 키워드로 색을 분기한다.
   *
   * @param {string} nameOrText - 도구명 ('web_search' 등) 또는 상태 문구 ('검색 중...' 등)
   */
  J.setToolColor = function (nameOrText) {
    const v = nameOrText || '';
    if (TOOL_COLOR_BY_NAME[v]) { J.state.toolColor = TOOL_COLOR_BY_NAME[v]; return; }
    if (v.includes('메모')) J.state.toolColor = TOOL_COLORS.vault;
    else if (v.includes('파일')) J.state.toolColor = TOOL_COLORS.file;
    else J.state.toolColor = TOOL_COLORS.web;
  };

})(window.JARVIS);