/**
 * 신경망 그래프 페이지
 */
'use strict';

/**
 * 1. 상수 — 레이아웃, 물리, BEM 클래스명
 */
const SIDEBAR_W = 260;
const HEADER_H  = 52;
const PI        = Math.PI;

// BEM 클래스명 상수
const CSS = Object.freeze({
  SIDEBAR_ITEM     : 'sidebar__item',
  SIDEBAR_INFO     : 'sidebar__item-info',
  SIDEBAR_KEYWORD  : 'sidebar__item-keyword',
  SIDEBAR_DATE     : 'sidebar__item-date',
  SIDEBAR_DEL      : 'sidebar__item-del',
  TOOLTIP          : 'node-tooltip',
  TOOLTIP_VISIBLE  : 'node-tooltip--visible',
  TOOLTIP_KEY      : 'node-tooltip__key',
  RESTORE_BTN      : 'restore-btn',
  RESTORE_BTN_VIS  : 'restore-btn--visible',
  RESTORE_OVL      : 'restore-overlay',
  RESTORE_OVL_VIS  : 'restore-overlay--visible',
  RESTORE_MOD      : 'restore-modal',
  RESTORE_MOD_VIS  : 'restore-modal--visible',
  RM_HEADER        : 'restore-modal__header',
  RM_TITLE         : 'restore-modal__title',
  RM_CLOSE         : 'restore-modal__close',
  RM_LIST          : 'restore-modal__list',
  RM_ITEM          : 'restore-modal__item',
  RM_INFO          : 'restore-modal__item-info',
  RM_KW            : 'restore-modal__item-kw',
  RM_DT            : 'restore-modal__item-dt',
  RM_BTN           : 'restore-modal__item-btn',
  RM_FOOTER        : 'restore-modal__footer',
  RM_ALL           : 'restore-modal__restore-all',
  SP_BODY_COLL     : 'status-panel__body--collapsed',
  SP_ARROW         : 'status-panel__arrow',
  SP_ARROW_UP      : 'status-panel__arrow--up',
});

/**
 * 캔버스 영역 크기를 반환합니다.
 * (사이드바·헤더 높이를 빼서 실제 렌더 영역만 계산)
 * 
 * @returns {{ w: number, h: number }}
 */
function getSize() {
  return { 
    w: window.innerWidth - SIDEBAR_W,
    h: window.innerHeight - HEADER_H };
}

/**
 * 채팅 페이지로 이동합니다.
 * 
 * @param {number|null} id - 이동할 세션 ID. null 이면 새 채팅
 */
function goToChat(id) { 
    window.location.href = id ? `/chat?id=${id}` : '/chat';
}

/**
 * 2. 상태
 */
let scene, camera, renderer, graphGroup;
let jarvisMeshes = [];
let nodeMeshes   = [];
let groupLines   = [];
let summaryGroups = {};
let clock        = 0;

// ── Lerp 기반 카메라 오빗 ──
const sphTgt = { theta: 0.3, phi: 1.25, radius: 13 };
const sphCur = { theta: 0.3, phi: 1.25, radius: 13 };
let tgtPos, curPos;

const LERP_DRAG = 0.22;
const LERP_IDLE = 0.10;

let isDragging = false;
let dragType   = null;
let hasDragged = false;
let prevMouse  = { x: 0, y: 0 };
let autoRotate = true;

/**
 * 3. 툴팁
 */
const tooltip = document.createElement('div');
tooltip.id        = 'nodeTooltip';
tooltip.className = CSS.TOOLTIP;

const ttLabel      = document.createElement('span');
ttLabel.className  = CSS.TOOLTIP_KEY;
ttLabel.textContent = 'summary';

const ttText       = document.createElement('span');
ttText.id          = 'ttText';

tooltip.appendChild(ttLabel);
tooltip.appendChild(ttText);
document.body.appendChild(tooltip);

/**
 * 3D 메시 위치를 화면 픽셀 좌표로 변환합니다.
 * 
 * @param {THREE.Mesh} mesh - 투영할 메시
 * @returns {{ x: number, y: number }} 화면 픽셀 좌표
 */
function toScreenPos(mesh) {
    const { w, h } = getSize();
    const v = mesh.position.clone().applyMatrix4(graphGroup.matrixWorld);
    v.project(camera);
    return { x: SIDEBAR_W + (v.x+1)/2*w, y: HEADER_H + (1-v.y)/2*h };
}

/**
 * 노드 위에 툴팁을 표시합니다.
 * 
 * @param {THREE.Mesh} mesh - 툴팁을 붙일 기준 메시
 * @param {string}     txt  - 표시할 텍스트
 */
function showTip(mesh, txt) {
    ttText.textContent = txt;
    const sp = toScreenPos(mesh);
    tooltip.style.left = sp.x + 'px';
    tooltip.style.top  = (sp.y - 48) + 'px';
    tooltip.classList.add(CSS.TOOLTIP_VISIBLE);
}

/**
 * 툴팁을 숨깁니다.
 */
function hideTip() { 
    tooltip.classList.remove(CSS.TOOLTIP_VISIBLE); 
}

/**
 * 4. 카메라 업데이트
 */
function updateCamera() {
    const s = sphCur;
    camera.position.set(
        curPos.x + s.radius * Math.sin(s.phi) * Math.sin(s.theta),
        curPos.y + s.radius * Math.cos(s.phi),
        curPos.z + s.radius * Math.sin(s.phi) * Math.cos(s.theta)
    );
    camera.lookAt(curPos);
}

/**
 * 5. 텍스처 생성
 * 
 * @returns 
 */
function makeCircleTex() {
    const c = document.createElement('canvas');
    c.width = c.height = 16;
    const ctx = c.getContext('2d');
    const g = ctx.createRadialGradient(8,8,0, 8,8,7);
    g.addColorStop(0,'rgba(255,255,255,1)');
    g.addColorStop(1,'rgba(255,255,255,0)');
    ctx.fillStyle = g; ctx.fillRect(0,0,16,16);
    return new THREE.CanvasTexture(c);
}

/**
 * 방사형 글로우 텍스처를 생성합니다.
 * 
 * @param {number} hexColor - 글로우 색상 (hex)
 * @param {number} [size=128] - 캔버스 해상도 (px)
 * @returns {THREE.CanvasTexture}
 */
function makeGlowTex(hexColor, size=128) {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');
    const col = new THREE.Color(hexColor);
    const r = Math.round(col.r*255), g = Math.round(col.g*255), b = Math.round(col.b*255);
    const grad = ctx.createRadialGradient(size/2,size/2,0, size/2,size/2,size/2);
    grad.addColorStop(0,   `rgba(255,255,255,1)`);
    grad.addColorStop(0.12, `rgba(${r},${g},${b},0.9)`);
    grad.addColorStop(0.5,  `rgba(${r},${g},${b},0.35)`);
    grad.addColorStop(1,   `rgba(0,0,0,0)`);
    ctx.fillStyle = grad; ctx.fillRect(0,0,size,size);
    return new THREE.CanvasTexture(c);
}

/**
 * 6. Three.js 초기화
 * 
 * @returns 
 */
function initThree() {
    if (typeof THREE === 'undefined') { console.error('[JARVIS] Three.js 로드 실패 — CDN 확인 필요'); return; }
    const cv = document.getElementById('graphCanvas');
    if (!cv) { console.error('[JARVIS] #graphCanvas 없음'); return; }

    // Lerp 벡터 초기화 (THREE 로드 확인 후)
    tgtPos = new THREE.Vector3(0, 0, 0);
    curPos = new THREE.Vector3(0, 0, 0);

    const { w, h } = getSize();
    renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.setSize(w, h);

    scene  = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(60, w/h, 0.1, 1000);
    updateCamera();

    scene.add(new THREE.AmbientLight(0x102040, 3));
    const pl = new THREE.PointLight(0x4fc3f7, 5, 100);
    pl.position.set(0, 0, 8);
    scene.add(pl);

    graphGroup = new THREE.Group();
    scene.add(graphGroup);

    addStarField();
    addJarvisNode();

    window.addEventListener('resize', () => {
        const { w, h } = getSize();
        renderer.setSize(w, h);
        camera.aspect = w/h;
        camera.updateProjectionMatrix();
    });
}


/**
 * 7. 씬 요소
 */

/**
 * 7-1. 별 배경
 */
function addStarField() {
    const tex = makeCircleTex();
    const n1=1400, p1=new Float32Array(n1*3), c1=new Float32Array(n1*3);
    for (let i=0; i<n1; i++) {
        p1[i*3]=(Math.random()-.5)*220; p1[i*3+1]=(Math.random()-.5)*220; p1[i*3+2]=(Math.random()-.5)*220;
        const t=Math.random();
        if(t<.55){c1[i*3]=.75;c1[i*3+1]=.85;c1[i*3+2]=1.0;}
        else if(t<.80){c1[i*3]=1.0;c1[i*3+1]=1.0;c1[i*3+2]=1.0;}
        else if(t<.93){c1[i*3]=.85;c1[i*3+1]=.70;c1[i*3+2]=1.0;}
        else{c1[i*3]=1.0;c1[i*3+1]=.95;c1[i*3+2]=.75;}
    }
    const g1=new THREE.BufferGeometry();
    g1.setAttribute('position',new THREE.BufferAttribute(p1,3));
    g1.setAttribute('color',   new THREE.BufferAttribute(c1,3));
    scene.add(new THREE.Points(g1, new THREE.PointsMaterial({map:tex,size:.22,transparent:true,opacity:.85,alphaTest:.05,vertexColors:true,depthWrite:false})));

    const n2=130, p2=new Float32Array(n2*3);
    for(let i=0;i<n2;i++){p2[i*3]=(Math.random()-.5)*90;p2[i*3+1]=(Math.random()-.5)*90;p2[i*3+2]=(Math.random()-.5)*90;}
    const g2=new THREE.BufferGeometry();
    g2.setAttribute('position',new THREE.BufferAttribute(p2,3));
    scene.add(new THREE.Points(g2, new THREE.PointsMaterial({map:tex,size:.5,transparent:true,opacity:.9,alphaTest:.05,color:0xddeeff,depthWrite:false})));
}

/**
 * 7-2 JARVIS 중앙 노드 — Arc Reactor
 */
function addJarvisNode() {
    const cyanTex   = makeGlowTex(0x4fc3f7, 128);
    const orangeTex = makeGlowTex(0xff6d3b, 128);
    const whiteTex  = makeGlowTex(0xffffff, 64);

    // ① 핵심 흰 코어 (아크리액터 중심)
    const core = new THREE.Mesh(
        new THREE.SphereGeometry(0.45, 32, 32),
        new THREE.MeshBasicMaterial({ color: 0xffffff })
    );
    core.userData = { type: 'jarvis' };
    graphGroup.add(core); jarvisMeshes.push(core);

    // ② 내부 시안 구체
    const inner = new THREE.Mesh(
        new THREE.SphereGeometry(0.85, 32, 32),
        new THREE.MeshBasicMaterial({ color: 0x4fc3f7, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending })
    );
    inner.userData = { type: 'jarvis' };
    graphGroup.add(inner); jarvisMeshes.push(inner);

    // ③ 오렌지 웜 글로우 (아크리액터 열기)
    const warmSp = new THREE.Sprite(new THREE.SpriteMaterial({ map: orangeTex, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending }));
    warmSp.scale.set(5, 5, 1);
    graphGroup.add(warmSp);

    // ④ 시안 주글로우
    const sp1 = new THREE.Sprite(new THREE.SpriteMaterial({ map: cyanTex, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending }));
    sp1.scale.set(9, 9, 1);
    graphGroup.add(sp1);

    // ⑤ 외부 대형 글로우
    const sp2 = new THREE.Sprite(new THREE.SpriteMaterial({ map: cyanTex, transparent: true, opacity: 0.18, blending: THREE.AdditiveBlending }));
    sp2.scale.set(20, 20, 1);
    graphGroup.add(sp2);

    // ⑥ 레이캐스트용 투명 구체
    const pick = new THREE.Mesh(
        new THREE.SphereGeometry(1.8, 16, 16),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0 })
    );
    pick.userData = { type: 'jarvis' };
    graphGroup.add(pick); jarvisMeshes.push(pick);

    const ringConfigs = [
        { r: 2.2, rx: Math.PI/8,  ry: 0,          rz: 0, speed:  0.50, axis: 'y' },
        { r: 2.7, rx: Math.PI/3,  ry: 0.5,        rz: 0, speed: -0.38, axis: 'y' },
        { r: 2.0, rx: Math.PI/2,  ry: Math.PI/4,  rz: 0, speed:  0.28, axis: 'x' },
    ];
    const jarvisRings = ringConfigs.map(({ r, rx, ry, rz, speed, axis }) => {
        const pts = [];
        for (let k = 0; k <= 64; k++) {
            const a = (k/64) * Math.PI * 2;
            pts.push(new THREE.Vector3(Math.cos(a)*r, Math.sin(a)*r, 0));
        }
        const ring = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(pts),
            new THREE.LineBasicMaterial({ color: 0x4fc3f7, transparent: true, opacity: 0.38 })
        );
        ring.rotation.set(rx, ry, rz);
        graphGroup.add(ring);
        return { ring, speed, axis };
    });

    graphGroup.userData.jCore      = core;
    graphGroup.userData.jInner     = inner;
    graphGroup.userData.jWarm      = warmSp;
    graphGroup.userData.jSp1       = sp1;
    graphGroup.userData.jSp2       = sp2;
    graphGroup.userData.jarvisRings = jarvisRings;
}

/**
 * 7-3. 세션 노드 (행성들)
 * 
 * @param {*} sessions 
 * @returns 
 */
function buildGraph(sessions) {
    // 기존 노드·글로우·연결선 제거
    nodeMeshes.forEach(n => {
        [n.mesh, n.glow, n.atmSprite, n.satRing].forEach(o => o && graphGroup.remove(o));
        if (n.line) graphGroup.remove(n.line);
    });
    groupLines.forEach(g => graphGroup.remove(g.line));
    nodeMeshes = [];
    groupLines = [];
    summaryGroups = {};

    const total  = sessions.length;
    if (!total) return;
    const radius = Math.max(6, Math.min(10, 5 + total * 0.08));

    // ── 노드 생성
    sessions.forEach((session, i) => {
        const basePos = fibSphere(i, total, radius);
        const age     = ageHours(session.last_active_at || session.started_at);
        const color   = nodeColor(age);
        const glowTex = makeGlowTex(color, 64);

        // 최근성 기반 크기 — 직관적 시각 계층
        const nodeR    = age < 1 ? 0.72 : age < 24 ? 0.58 : age < 168 ? 0.48 : 0.38;
        const glowOpa  = age < 1 ? 0.9  : age < 24 ? 0.75 : age < 168 ? 0.6  : 0.45;
        const atmScale = nodeR * 5.5;

        const mesh = new THREE.Mesh(
            new THREE.SphereGeometry(nodeR, 24, 24),
            new THREE.MeshPhongMaterial({
                color,
                emissive : new THREE.Color(color).multiplyScalar(0.65),
                shininess: 90,
                specular : new THREE.Color(0x4fc3f7),
            })
        );
        mesh.position.copy(basePos);
        mesh.userData = { type: 'session', session };
        graphGroup.add(mesh);

        const atm = new THREE.Sprite(new THREE.SpriteMaterial({
            map: glowTex, transparent: true,
            opacity: glowOpa, blending: THREE.AdditiveBlending,
        }));
        atm.scale.set(atmScale, atmScale, 1);
        atm.position.copy(basePos);
        graphGroup.add(atm);

        // 중앙(JARVIS) 연결선 — 밝기 개선
        const linePts = new Float32Array(6);
        linePts[3] = basePos.x; linePts[4] = basePos.y; linePts[5] = basePos.z;
        const lineGeo = new THREE.BufferGeometry();
        lineGeo.setAttribute('position', new THREE.BufferAttribute(linePts, 3));
        const line = new THREE.Line(lineGeo,
            new THREE.LineBasicMaterial({ color: 0x1a4a7c, transparent: true, opacity: 0.55 }));
        graphGroup.add(line);

        // 홀로그램 궤도 링 (토성 고리 스타일)
        const satPts = [];
        for (let k = 0; k <= 48; k++) {
            const a = (k/48) * Math.PI * 2;
            satPts.push(new THREE.Vector3(Math.cos(a)*(nodeR*2.4), Math.sin(a)*(nodeR*2.4), 0));
        }
        const satRing = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(satPts),
            new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.5 })
        );
        satRing.position.copy(basePos);
        satRing.rotation.x = 0.9;
        satRing.rotation.z = i * 0.7;
        graphGroup.add(satRing);

        nodeMeshes.push({ mesh, atmSprite: atm, satRing, glow: null, line,
            basePos: basePos.clone(), vel: new THREE.Vector3(), session });

        // summary 그룹 인덱스 등록
        const key = session.summary || '_';
        if (!summaryGroups[key]) summaryGroups[key] = [];
        summaryGroups[key].push(i);
    });

    // ── 같은 summary 노드 간 연결선
    const connected = new Set();

    Object.values(summaryGroups).forEach(indices => {
        if (indices.length < 2) return;

        indices.forEach(i => {
            const posI = nodeMeshes[i].mesh.position;

            // 같은 그룹 내 거리 기준 정렬 → 가장 가까운 2개 연결
            const nearest = indices
                .filter(j => j !== i)
                .map(j => ({ j, d: posI.distanceTo(nodeMeshes[j].mesh.position) }))
                .sort((a, b) => a.d - b.d)
                .slice(0, 2);

            nearest.forEach(({ j }) => {
                const key = Math.min(i, j) + ':' + Math.max(i, j);
                if (connected.has(key)) return;
                connected.add(key);

                const posA = nodeMeshes[i].mesh.position;
                const posB = nodeMeshes[j].mesh.position;
                const pts  = new Float32Array(6);
                pts[0]=posA.x; pts[1]=posA.y; pts[2]=posA.z;
                pts[3]=posB.x; pts[4]=posB.y; pts[5]=posB.z;

                const geo  = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.BufferAttribute(pts, 3));
                const gline = new THREE.Line(geo,
                    new THREE.LineBasicMaterial({ color: 0x4fc3f7, transparent: true, opacity: 0.35 }));
                graphGroup.add(gline);
                groupLines.push({ line: gline, i, j });
            });
        });
    });
}

/**
 * 7-4. 물리 시뮬레이션 (용수철 + 반발 + 진동 + 그룹 인력)
 */
function updatePhysics() {
    const K_SPRING  = 0.018;
    const K_REPULSE = 0.10;
    const K_GROUP   = 0.006;
    const DAMPING   = 0.86;
    const OSC_AMP   = 0.004;

    nodeMeshes.forEach((a, i) => {
        const f = new THREE.Vector3();

        // 1. 기준 위치(fibonacci sphere)로의 용수철
        f.addScaledVector(a.basePos.clone().sub(a.mesh.position), K_SPRING);

        // 2. 유기적 진동 (노드마다 다른 위상)
        const ph = i * 2.17 + clock * 0.35;
        f.x += Math.sin(ph)       * OSC_AMP;
        f.y += Math.cos(ph * 1.3) * OSC_AMP;
        f.z += Math.sin(ph * 0.7) * OSC_AMP * 0.6;

        // 3. 주변 노드 반발
        for (let j = 0; j < nodeMeshes.length; j++) {
            if (i === j) continue;
            const diff = a.mesh.position.clone().sub(nodeMeshes[j].mesh.position);
            const d2   = diff.lengthSq();
            if (d2 < 9 && d2 > 0.01) f.addScaledVector(diff.normalize(), K_REPULSE / d2);
        }

        // 4. 같은 summary 그룹 노드 간 약한 인력 (클러스터링)
        const myKey = a.session.summary || '_';
        const peers = summaryGroups[myKey];
        if (peers && peers.length > 1) {
            peers.forEach(j => {
                if (j === i) return;
                const diff = nodeMeshes[j].mesh.position.clone().sub(a.mesh.position);
                const dist = diff.length();
                // 너무 가까우면 무시, 너무 멀면 무시 (자연스러운 클러스터 간격 유지)
                if (dist > 1.5 && dist < 7) {
                    f.addScaledVector(diff.normalize(), K_GROUP);
                }
            });
        }

        a.vel.add(f).multiplyScalar(DAMPING);
        a.mesh.position.add(a.vel);

        if (a.atmSprite) a.atmSprite.position.copy(a.mesh.position);
        if (a.satRing) {
            a.satRing.position.copy(a.mesh.position);
            a.satRing.rotation.y += 0.018;
        }

        // 중앙 연결선 끝점 업데이트
        if (a.line) {
            const p = a.line.geometry.attributes.position;
            p.setXYZ(1, a.mesh.position.x, a.mesh.position.y, a.mesh.position.z);
            p.needsUpdate = true;
        }
    });

    // 5. 그룹 연결선 양 끝점 업데이트
    groupLines.forEach(({ line, i, j }) => {
        const pA = nodeMeshes[i].mesh.position;
        const pB = nodeMeshes[j].mesh.position;
        const p  = line.geometry.attributes.position;
        p.setXYZ(0, pA.x, pA.y, pA.z);
        p.setXYZ(1, pB.x, pB.y, pB.z);
        p.needsUpdate = true;
    });
}

/**
 * 8. 헬퍼
 * 
 * @param {*} i 
 * @param {*} n 
 * @param {*} r 
 * @returns 
 */
function fibSphere(i, n, r) {
    const phi   = 2*PI*i / ((1+Math.sqrt(5))/2);
    const theta = Math.acos(1 - 2*(i+0.5)/n);
    return new THREE.Vector3(Math.sin(theta)*Math.cos(phi)*r, Math.sin(theta)*Math.sin(phi)*r, Math.cos(theta)*r);
}

/**
 * 노드의 색상을 결정합니다.
 * @param {*} h 
 * @returns 
 */
function nodeColor(h) {
    if (h<1)   return 0x00e5ff;
    if (h<24)  return 0x4fc3f7;
    if (h<168) return 0x1976d2;
    return 0x0d47a1;
}

/**
 * 카메라 위경도(phi)를 극점에 걸리지 않도록 클램프합니다.
 * 
 * @param {number} v - 클램프할 phi 값 (rad)
 * @returns {number} 클램프된 phi 값
 */
function clampPhi(v) { 
    return Math.max(0.06, Math.min(PI-0.06, v)); 
}

/**
 * 9. 이벤트
 */
function bindEvents() {
    const canvas    = document.getElementById('graphCanvas');
    const raycaster = new THREE.Raycaster();
    const mouse2d   = new THREE.Vector2();

    function allPick() { return [...jarvisMeshes, ...nodeMeshes.map(n => n.mesh)]; }
    function toNDC(e, rect) {
        mouse2d.x = ((e.clientX-rect.left)/rect.width)*2-1;
        mouse2d.y = -((e.clientY-rect.top)/rect.height)*2+1;
    }

    // ── 마우스 다운 (왼쪽=오빗, 오른쪽/휠=패닝)
    canvas.addEventListener('mousedown', e => {
        isDragging = true; hasDragged = false;
        prevMouse  = { x: e.clientX, y: e.clientY };
        dragType   = (e.button===2||e.button===1) ? 'pan' : 'orbit';
        if (dragType === 'orbit') autoRotate = false;
        canvas.style.cursor = dragType==='pan' ? 'move' : 'grabbing';
    });
    canvas.addEventListener('contextmenu', e => e.preventDefault());

    // ── 마우스 이동
    window.addEventListener('mousemove', e => {
        if (!isDragging) {
            const rect = canvas.getBoundingClientRect();
            if (e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom) { hideTip(); return; }
            toNDC(e, rect);
            raycaster.setFromCamera(mouse2d, camera);
            const hits = raycaster.intersectObjects(allPick());
            if (hits.length) {
                canvas.style.cursor = 'pointer';
                const obj = hits[0].object;
                if (obj.userData.type==='session') showTip(obj, obj.userData.session.summary || fmtDate(obj.userData.session.started_at));
                else hideTip();
            } else { canvas.style.cursor='grab'; hideTip(); }
            return;
        }

        const dx = e.clientX - prevMouse.x;
        const dy = e.clientY - prevMouse.y;
        if (Math.abs(dx)+Math.abs(dy) > 2) hasDragged = true;

        if (dragType === 'orbit') {
            sphTgt.theta -= dx * 0.007;
            sphTgt.phi    = clampPhi(sphTgt.phi + dy * 0.007);
        } else {
            // 패닝: 카메라 로컬 평면으로 target 이동
            const { w, h } = getSize();
            const fwd = new THREE.Vector3(); camera.getWorldDirection(fwd);
            const rgt = new THREE.Vector3().crossVectors(fwd, camera.up).normalize();
            const up  = new THREE.Vector3().crossVectors(rgt, fwd).normalize();
            tgtPos.addScaledVector(rgt, -dx/w * sphTgt.radius * 2);
            tgtPos.addScaledVector(up,   dy/h * sphTgt.radius * 2);
        }
        prevMouse = { x: e.clientX, y: e.clientY };
    });

    // ── 마우스 업
    window.addEventListener('mouseup', () => {
        if (dragType==='orbit') setTimeout(() => { autoRotate=true; }, 2800);
        isDragging=false; dragType=null;
        canvas.style.cursor='grab';
    });

    // ── 줌
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        sphTgt.radius = Math.max(4, Math.min(40, sphTgt.radius + e.deltaY * 0.022));
    }, { passive: false });

    // ── 클릭 → 채팅
    canvas.addEventListener('click', e => {
        if (hasDragged) return;
        hideTip();
        const rect = canvas.getBoundingClientRect();
        toNDC(e, rect);
        raycaster.setFromCamera(mouse2d, camera);
        const hits = raycaster.intersectObjects(allPick());
        if (!hits.length) return;
        const obj = hits[0].object;
        if (obj.userData.type==='jarvis') goToChat(null);
        else goToChat(obj.userData.session.session_id);
    });

    // ── 터치 (1손가락=오빗, 2손가락=줌)
    let lt = [];
    canvas.addEventListener('touchstart', e => {
        lt=[...e.touches].map(t=>({x:t.clientX,y:t.clientY}));
        hasDragged=false; autoRotate=false;
    }, { passive:true });
    canvas.addEventListener('touchmove', e => {
        e.preventDefault();
        const ts=[...e.touches].map(t=>({x:t.clientX,y:t.clientY}));
        if (ts.length===1 && lt.length>=1) {
            sphTgt.theta -= (ts[0].x-lt[0].x) * 0.007;
            sphTgt.phi    = clampPhi(sphTgt.phi + (ts[0].y-lt[0].y) * 0.007);
            hasDragged=true;
        } else if (ts.length===2 && lt.length>=2) {
            const pd = Math.hypot(lt[1].x-lt[0].x, lt[1].y-lt[0].y);
            const cd = Math.hypot(ts[1].x-ts[0].x, ts[1].y-ts[0].y);
            sphTgt.radius = Math.max(4, Math.min(40, sphTgt.radius - (cd-pd)*0.05));
        }
        lt=ts;
    }, { passive:false });
    canvas.addEventListener('touchend', () => { setTimeout(()=>{autoRotate=true;},2800); });
}

/**
 * 10. 애니메이션 루프
 */
function startAnimation() {
    function loop() {
        requestAnimationFrame(loop);
        clock += 0.016;

        // ── 자동 공전
        if (autoRotate && !isDragging) sphTgt.theta += 0.0008;

        // ── Lerp 보간
        const lerp = isDragging ? LERP_DRAG : LERP_IDLE;
        sphCur.theta  += (sphTgt.theta  - sphCur.theta)  * lerp;
        sphCur.phi    += (sphTgt.phi    - sphCur.phi)    * lerp;
        sphCur.radius += (sphTgt.radius - sphCur.radius) * lerp;
        curPos.lerp(tgtPos, lerp);
        updateCamera();

        // ── 물리 업데이트
        updatePhysics();

        // ── JARVIS 아크리액터 맥동
        const p = 1 + Math.sin(clock * 2.0) * 0.065;
        const pw = 1 + Math.sin(clock * 0.9) * 0.12;
        const { jCore, jInner, jWarm, jSp1, jSp2, jarvisRings } = graphGroup.userData;
        if (jCore)  jCore.scale.setScalar(p);
        if (jInner) { jInner.scale.setScalar(p * 1.1); jInner.material.opacity = 0.7 + Math.sin(clock*2.0)*0.15; }
        if (jWarm)  { jWarm.scale.setScalar(4.5 + Math.sin(clock*0.9)*1.0); jWarm.material.opacity = 0.28 + Math.sin(clock*0.9)*0.12; }
        if (jSp1)   { jSp1.scale.setScalar(8.5 + Math.sin(clock*2.0)*1.4); jSp1.material.opacity  = 0.8 + Math.sin(clock*2.0)*0.18; }
        if (jSp2)   { jSp2.scale.setScalar(18  + Math.sin(clock*0.8)*2.5); jSp2.material.opacity  = 0.14 + Math.sin(clock*0.8)*0.05; }

        // ── JARVIS 홀로그램 궤도 링 회전 (axis별 다른 방향)
        if (jarvisRings) {
            jarvisRings.forEach(({ ring, speed, axis }) => {
                ring.rotation[axis] += speed * 0.016;
            });
        }

        renderer.render(scene, camera);
    }
    loop();
}

/**
 * 11. 숨기기 (localStorage 기반 — DB 무영향)
 */
const HIDDEN_KEY = 'jarvis_hidden_sessions';
let   _allSessions = []; 

/**
 * localStorage에서 숨긴 세션 ID Set을 읽어 반환합니다.
 * 
 * @returns {Set<number>}
 */
function getHidden() {
    try { return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); }
    catch { return new Set(); }
}

/**
 * 세션을 숨김 목록에 추가합니다. (DB에는 영향 없음)
 * 
 * @param {number} id - 숨길 세션 ID
 */
function hideSession(id) {
    const s = getHidden(); s.add(id);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
}

/**
 * 숨김 목록에서 세션을 제거합니다.
 *
 * @param {number} id - 복원할 세션 ID
 */
function restoreSession(id) {
    const s = getHidden(); s.delete(id);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
}

/**
 * 모든 숨김 세션을 복원합니다. (localStorage 키 삭제)
 */
function restoreAll() {
    localStorage.removeItem(HIDDEN_KEY);
}

/**
 * 복원 모달 (숨긴 세션 목록 → 개별/전체 복원)
 */
function showRestoreModal() {
    const hidden     = getHidden();
    const hiddenList = _allSessions.filter(s => hidden.has(s.session_id));

    // 배경 오버레이 (클릭 시 닫기)
    let overlay = document.getElementById('restoreOverlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'restoreOverlay';
        overlay.className = CSS.RESTORE_OVL;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', closeRestoreModal);
    }

    let modal = document.getElementById('restoreModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'restoreModal';
        modal.className = CSS.RESTORE_MOD;
        document.body.appendChild(modal);
    }

    // ── DOM API로 구성
    modal.replaceChildren();

    // 헤더
    const hdr   = document.createElement('div'); hdr.className = CSS.RM_HEADER;
    const title = document.createElement('span'); title.className = CSS.RM_TITLE;
    title.textContent = `숨긴 세션 (${hiddenList.length}개)`;
    const closeBtn = document.createElement('button'); closeBtn.className = CSS.RM_CLOSE;
    closeBtn.textContent = '×';
    closeBtn.onclick = closeRestoreModal;
    hdr.appendChild(title); hdr.appendChild(closeBtn);

    // 목록
    const list = document.createElement('div'); list.className = CSS.RM_LIST;
    hiddenList.forEach(s => {
        const item = document.createElement('div');
        item.className = CSS.RM_ITEM; item.dataset.id = s.session_id;

        const info = document.createElement('div'); info.className = CSS.RM_INFO;
        const kw   = document.createElement('span'); kw.className = CSS.RM_KW;
        kw.textContent = s.summary || '···';
        const dt   = document.createElement('span'); dt.className = CSS.RM_DT;
        dt.textContent = fmtDate(s.last_active_at || s.started_at);
        info.appendChild(kw); info.appendChild(dt);

        const btn = document.createElement('button'); btn.className = CSS.RM_BTN;
        btn.textContent = '↩ 복원';
        btn.onclick = () => {
            restoreSession(parseInt(item.dataset.id, 10));
            _lastSessionsJson = '';
            loadSessions();
            if (getHidden().size > 0) showRestoreModal();
            else closeRestoreModal();
        };

        item.appendChild(info); item.appendChild(btn);
        list.appendChild(item);
    });

    // 푸터
    const footer  = document.createElement('div'); footer.className = CSS.RM_FOOTER;
    const allBtn  = document.createElement('button'); allBtn.className = CSS.RM_ALL;
    allBtn.textContent = '↩ 전체 복원';
    allBtn.onclick = () => { restoreAll(); _lastSessionsJson = ''; loadSessions(); closeRestoreModal(); };
    footer.appendChild(allBtn);

    modal.appendChild(hdr); modal.appendChild(list); modal.appendChild(footer);

    overlay.classList.add(CSS.RESTORE_OVL_VIS);
    modal.classList.add(CSS.RESTORE_MOD_VIS);
}

/**
 * 복원 모달과 배경 오버레이를 닫습니다.
 */
function closeRestoreModal() {
    const modal   = document.getElementById('restoreModal');
    const overlay = document.getElementById('restoreOverlay');
    if (modal)   modal.classList.remove(CSS.RESTORE_MOD_VIS);
    if (overlay) overlay.classList.remove(CSS.RESTORE_OVL_VIS);
}

/**
 *  우측 하단 플로팅 복원 버튼
 * 
 * @param {*} count 
 */
function updateRestoreBtn(count) {
    let btn = document.getElementById('restoreBtn');
    if (!btn) {
        btn = document.createElement('div');
        btn.id = 'restoreBtn';
        btn.className = CSS.RESTORE_BTN;
        document.body.appendChild(btn);
    }
    btn.onclick = showRestoreModal;
    if (count > 0) {
        btn.textContent = `↩  숨긴 세션 ${count}개`;
        btn.classList.add(CSS.RESTORE_BTN_VIS);
    } else {
        btn.classList.remove(CSS.RESTORE_BTN_VIS);
        closeRestoreModal();
    }
}

/**
 * 12. 사이드바
 * 세션 목록을 사이드바에 렌더링합니다. (최대 50개)
 * 
 * @param {Array<Object>} sessions - 표시할 세션 배열
 */
function buildSidebar(sessions) {
    const c = document.getElementById('sidebarSessions');
    c.replaceChildren();

    sessions.slice(0, 50).forEach(s => {
        const item = document.createElement('div');
        item.className = CSS.SIDEBAR_ITEM;

        const info = document.createElement('div');
        info.className = CSS.SIDEBAR_INFO;

        const kw = document.createElement('span'); kw.className = CSS.SIDEBAR_KEYWORD;
        kw.textContent = s.summary||'···';

        const dt = document.createElement('span'); dt.className = CSS.SIDEBAR_DATE;
        dt.textContent = fmtDate(s.last_active_at||s.started_at);

        info.appendChild(kw); info.appendChild(dt);

        const del = document.createElement('button');
        del.className = CSS.SIDEBAR_DEL;
        del.textContent = '×';
        del.title       = '목록에서 숨기기 (DB 유지)';
        del.addEventListener('click', e => {
            e.stopPropagation();
            hideSession(s.session_id);
            _lastSessionsJson = '';
            loadSessions();
        });

        item.appendChild(info);
        item.appendChild(del);
        item.addEventListener('click', () => goToChat(s.session_id));
        c.appendChild(item);
    });

    // 우측 하단 플로팅 복원 버튼 업데이트
    updateRestoreBtn(getHidden().size);
}

/**
 * 13. 초기화 + 자동 갱신
 */
let _lastSessionsJson = '';

async function loadSessions() {
    try {
        const all     = await apiFetch(API_ENDPOINTS.sessions);
        _allSessions  = all;
        const hidden  = getHidden();
        const visible = all.filter(s => !hidden.has(s.session_id));
        const json    = JSON.stringify(visible);

        if (json !== _lastSessionsJson) {
            _lastSessionsJson = json;
            buildGraph(visible);
            buildSidebar(visible);
        }
        updateStatusPanel(all);
    } catch(e) { console.error('세션 로드 실패', e); }
}

/**
 * 상태 패널의 통계 수치(전체·오늘·이번 주·마지막 활성)를 갱신합니다.
 * 
 * @param {Array<Object>} sessions - 전체 세션 배열
 */
function updateStatusPanel(sessions) {
    const total = sessions.length;
    const today = sessions.filter(s => ageHours(s.last_active_at || s.started_at) < 24).length;
    const week  = sessions.filter(s => ageHours(s.last_active_at || s.started_at) < 168).length;

    let lastStr = '—';
    if (sessions.length) {
        const latest = sessions.reduce((a, b) => {
            const ta = new Date(a.last_active_at || a.started_at).getTime();
            const tb = new Date(b.last_active_at || b.started_at).getTime();
            return ta > tb ? a : b;
        });
        const h = ageHours(latest.last_active_at || latest.started_at);
        if (h < 1)       lastStr = Math.round(h * 60) + 'M AGO';
        else if (h < 24) lastStr = Math.round(h) + 'H AGO';
        else             lastStr = Math.round(h / 24) + 'D AGO';
    }

    const $ = id => document.getElementById(id);
    if ($('spTotal')) $('spTotal').textContent = total;
    if ($('spToday')) $('spToday').textContent = today;
    if ($('spWeek'))  $('spWeek').textContent  = week;
    if ($('spLast'))  $('spLast').textContent  = lastStr;
}

/**
 * status panel 접기/펼치기
 * 
 * @returns 
 */
function initStatusPanelToggle() {
    const toggle = document.getElementById('spToggle');
    const body   = document.getElementById('spBody');
    if (!toggle || !body) return;
    const arrow  = toggle.querySelector('.' + CSS.SP_ARROW);

    toggle.addEventListener('click', () => {
        const isCollapsed = body.classList.toggle(CSS.SP_BODY_COLL);
        if (arrow) arrow.classList.toggle(CSS.SP_ARROW_UP, !isCollapsed);
    });
}

/**
 * 페이지 초기화 — Three.js·이벤트·애니메이션·세션 데이터를 순서대로 구동합니다.
 */
async function init() {
    initThree();
    bindEvents();
    startAnimation();
    initStatusPanelToggle();
    await loadSessions();

    // 탭으로 돌아올 때 즉시 갱신
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') loadSessions();
    });

    // 60초마다 백그라운드 polling 
    setInterval(loadSessions, 60_000);
}

init();