// ═══════════════════════════════════════════════════════════════
// 1. 상수
// ═══════════════════════════════════════════════════════════════
const SIDEBAR_W  = 240;
const HEADER_H   = 56;
const PI         = Math.PI;

function getSize() {
    return { w: window.innerWidth - SIDEBAR_W, h: window.innerHeight - HEADER_H };
}

const API_SESSIONS = '/api/v1/chat/sessions';
function goToChat(id) { window.location.href = id ? `/chat?id=${id}` : '/chat'; }


// ═══════════════════════════════════════════════════════════════
// 2. 상태
// ═══════════════════════════════════════════════════════════════
let scene, camera, renderer, graphGroup;
let jarvisMeshes = [];   // for raycasting
let nodeMeshes   = [];
let groupLines   = [];   // 같은 summary 노드 간 연결선
let summaryGroups = {};  // summary → [index] 맵
let clock        = 0;

// ── Lerp 기반 카메라 오빗 ──
const sphTgt = { theta: 0.3, phi: 1.25, radius: 15 };
const sphCur = { theta: 0.3, phi: 1.25, radius: 15 };
let tgtPos, curPos;  // initThree()에서 new THREE.Vector3() 초기화

const LERP_DRAG = 0.22;   // 드래그 중 빠른 추종
const LERP_IDLE = 0.10;   // 드래그 후 부드러운 감속

let isDragging = false;
let dragType   = null;    // 'orbit' | 'pan'
let hasDragged = false;
let prevMouse  = { x: 0, y: 0 };
let autoRotate = true;


// ═══════════════════════════════════════════════════════════════
// 3. 툴팁
// ═══════════════════════════════════════════════════════════════
const tooltip = document.createElement('div');
tooltip.id = 'nodeTooltip';
tooltip.innerHTML = '<span class="tt-key">summary</span><span id="ttText"></span>';
document.body.appendChild(tooltip);
const ttText = document.getElementById('ttText');

function toScreenPos(mesh) {
    const { w, h } = getSize();
    const v = mesh.position.clone().applyMatrix4(graphGroup.matrixWorld);
    v.project(camera);
    return { x: SIDEBAR_W + (v.x+1)/2*w, y: HEADER_H + (1-v.y)/2*h };
}
function showTip(mesh, txt) {
    ttText.textContent = txt;
    const sp = toScreenPos(mesh);
    tooltip.style.left = sp.x + 'px';
    tooltip.style.top  = (sp.y - 48) + 'px';
    tooltip.classList.add('visible');
}
function hideTip() { tooltip.classList.remove('visible'); }


// ═══════════════════════════════════════════════════════════════
// 4. 카메라 업데이트
// ═══════════════════════════════════════════════════════════════
function updateCamera() {
    const s = sphCur;
    camera.position.set(
        curPos.x + s.radius * Math.sin(s.phi) * Math.sin(s.theta),
        curPos.y + s.radius * Math.cos(s.phi),
        curPos.z + s.radius * Math.sin(s.phi) * Math.cos(s.theta)
    );
    camera.lookAt(curPos);
}


// ═══════════════════════════════════════════════════════════════
// 5. 텍스처 생성
// ═══════════════════════════════════════════════════════════════
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


// ═══════════════════════════════════════════════════════════════
// 6. Three.js 초기화
// ═══════════════════════════════════════════════════════════════
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


// ═══════════════════════════════════════════════════════════════
// 7. 씬 요소
// ═══════════════════════════════════════════════════════════════

// ── 7-1. 별 배경 ──
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

// ── 7-2. JARVIS 중앙 노드 (항성) ──
function addJarvisNode() {
    const glowTex = makeGlowTex(0x4fc3f7, 128);

    // 밝은 코어
    const core = new THREE.Mesh(
        new THREE.SphereGeometry(0.65, 32, 32),
        new THREE.MeshBasicMaterial({ color: 0xffffff })
    );
    core.userData = { type: 'jarvis' };
    graphGroup.add(core);
    jarvisMeshes.push(core);

    // 내부 색구체
    const mid = new THREE.Mesh(
        new THREE.SphereGeometry(1.1, 32, 32),
        new THREE.MeshBasicMaterial({ color: 0x4fc3f7, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending })
    );
    mid.userData = { type: 'jarvis' };
    graphGroup.add(mid);
    jarvisMeshes.push(mid);

    // 글로우 스프라이트 (내부)
    const sp1 = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending }));
    sp1.scale.set(9, 9, 1);
    graphGroup.add(sp1);

    // 글로우 스프라이트 (외부, 넓게)
    const sp2 = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, opacity: 0.2, blending: THREE.AdditiveBlending }));
    sp2.scale.set(18, 18, 1);
    graphGroup.add(sp2);

    // 레이캐스트용 투명 구체
    const pick = new THREE.Mesh(
        new THREE.SphereGeometry(1.8, 16, 16),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0 })
    );
    pick.userData = { type: 'jarvis' };
    graphGroup.add(pick);
    jarvisMeshes.push(pick);

    // 애니메이션 참조
    graphGroup.userData.jarvisCore = core;
    graphGroup.userData.jarvisMid  = mid;
    graphGroup.userData.jarvisSp1  = sp1;
    graphGroup.userData.jarvisSp2  = sp2;
}

// ── 7-3. 세션 노드 (행성들) ──
function buildGraph(sessions) {
    // 기존 노드·글로우·연결선 제거
    nodeMeshes.forEach(n => {
        [n.mesh, n.glow, n.atmSprite].forEach(o => o && graphGroup.remove(o));
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

        const mesh = new THREE.Mesh(
            new THREE.SphereGeometry(0.42, 24, 24),
            new THREE.MeshPhongMaterial({
                color,
                emissive : new THREE.Color(color).multiplyScalar(0.5),
                shininess: 80,
                specular : new THREE.Color(0x4fc3f7),
            })
        );
        mesh.position.copy(basePos);
        mesh.userData = { type: 'session', session };
        graphGroup.add(mesh);

        const atm = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, transparent: true, blending: THREE.AdditiveBlending }));
        atm.scale.set(2.4, 2.4, 1);
        atm.position.copy(basePos);
        graphGroup.add(atm);

        // 중앙(JARVIS) 연결선
        const linePts = new Float32Array(6);
        linePts[3] = basePos.x; linePts[4] = basePos.y; linePts[5] = basePos.z;
        const lineGeo = new THREE.BufferGeometry();
        lineGeo.setAttribute('position', new THREE.BufferAttribute(linePts, 3));
        const line = new THREE.Line(lineGeo,
            new THREE.LineBasicMaterial({ color: 0x0d2240, transparent: true, opacity: 0.35 }));
        graphGroup.add(line);

        nodeMeshes.push({ mesh, atmSprite: atm, glow: null, line,
            basePos: basePos.clone(), vel: new THREE.Vector3(), session });

        // summary 그룹 인덱스 등록
        const key = session.summary || '_';
        if (!summaryGroups[key]) summaryGroups[key] = [];
        summaryGroups[key].push(i);
    });

    // ── 같은 summary 노드 간 연결선
    // 각 노드에서 같은 그룹 내 가장 가까운 2개와만 연결 (선 폭발 방지)
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

// ── 7-4. 물리 시뮬레이션 (용수철 + 반발 + 진동 + 그룹 인력) ──
function updatePhysics() {
    const K_SPRING  = 0.018;
    const K_REPULSE = 0.10;
    const K_GROUP   = 0.006;   // 같은 summary 간 인력
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


// ═══════════════════════════════════════════════════════════════
// 8. 헬퍼
// ═══════════════════════════════════════════════════════════════
function fibSphere(i, n, r) {
    const phi   = 2*PI*i / ((1+Math.sqrt(5))/2);
    const theta = Math.acos(1 - 2*(i+0.5)/n);
    return new THREE.Vector3(Math.sin(theta)*Math.cos(phi)*r, Math.sin(theta)*Math.sin(phi)*r, Math.cos(theta)*r);
}
function nodeColor(h) {
    if (h<1)   return 0x4fc3f7;
    if (h<24)  return 0x29b6f6;
    if (h<168) return 0x0288d1;
    return 0x1565c0;
}
function ageHours(d) {
    if (!d) return 9999;
    return (Date.now() - new Date(d.endsWith('Z')?d:d+'Z').getTime()) / 3600000;
}
function fmtDate(d) {
    if (!d) return '---';
    const dt = new Date(d.endsWith('Z')?d:d+'Z');
    return `${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')} ${String(dt.getHours()).padStart(2,'0')}:${String(dt.getMinutes()).padStart(2,'0')}`;
}
function clampPhi(v) { return Math.max(0.06, Math.min(PI-0.06, v)); }


// ═══════════════════════════════════════════════════════════════
// 9. 이벤트 (Lerp 방식 — input은 sphTgt만 수정, 렌더는 animation loop)
// ═══════════════════════════════════════════════════════════════
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

    // ── 마우스 이동 (sphTgt 만 수정 — updateCamera는 animation loop 담당)
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

    // ── 줌 (sphTgt.radius만 수정)
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


// ═══════════════════════════════════════════════════════════════
// 10. 애니메이션 루프
// ═══════════════════════════════════════════════════════════════
function startAnimation() {
    function loop() {
        requestAnimationFrame(loop);
        clock += 0.016;

        // ── 자동 공전
        if (autoRotate && !isDragging) sphTgt.theta += 0.0008;

        // ── Lerp 보간 (부드러운 이동)
        const lerp = isDragging ? LERP_DRAG : LERP_IDLE;
        sphCur.theta  += (sphTgt.theta  - sphCur.theta)  * lerp;
        sphCur.phi    += (sphTgt.phi    - sphCur.phi)    * lerp;
        sphCur.radius += (sphTgt.radius - sphCur.radius) * lerp;
        curPos.lerp(tgtPos, lerp);
        updateCamera();

        // ── 물리 업데이트
        updatePhysics();

        // ── JARVIS 항성 맥동
        const p = 1 + Math.sin(clock * 1.8) * 0.06;
        const { jarvisCore, jarvisMid, jarvisSp1, jarvisSp2 } = graphGroup.userData;
        if (jarvisCore) jarvisCore.scale.setScalar(p);
        if (jarvisMid)  jarvisMid.scale.setScalar(p);
        if (jarvisSp1)  { jarvisSp1.scale.setScalar(8 + Math.sin(clock*1.8)*1.2); jarvisSp1.material.opacity = 0.75 + Math.sin(clock*1.8)*0.15; }
        if (jarvisSp2)  { jarvisSp2.scale.setScalar(16 + Math.sin(clock*0.9)*2);  jarvisSp2.material.opacity = 0.14 + Math.sin(clock*0.9)*0.05; }

        renderer.render(scene, camera);
    }
    loop();
}


// ═══════════════════════════════════════════════════════════════
// 11. 숨기기 (localStorage 기반 — DB 무영향)
// ═══════════════════════════════════════════════════════════════
const HIDDEN_KEY = 'jarvis_hidden_sessions';
let   _allSessions = [];   // 전체 세션 캐시 (모달에서 hidden 목록 표시용)

function getHidden() {
    try { return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]')); }
    catch { return new Set(); }
}
function hideSession(id) {
    const s = getHidden(); s.add(id);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
}
function restoreSession(id) {
    const s = getHidden(); s.delete(id);
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
}
function restoreAll() {
    localStorage.removeItem(HIDDEN_KEY);
}


// ── 복원 모달 (숨긴 세션 목록 → 개별/전체 복원)
function showRestoreModal() {
    const hidden     = getHidden();
    const hiddenList = _allSessions.filter(s => hidden.has(s.session_id));

    // 배경 오버레이 (클릭 시 닫기)
    let overlay = document.getElementById('restoreOverlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'restoreOverlay';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', closeRestoreModal);
    }

    let modal = document.getElementById('restoreModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'restoreModal';
        document.body.appendChild(modal);
    }

    const items = hiddenList.map(s => `
        <div class="rm-item" data-id="${s.session_id}">
            <div class="rm-info">
                <span class="rm-kw">${s.summary || '···'}</span>
                <span class="rm-dt">${fmtDate(s.last_active_at || s.started_at)}</span>
            </div>
            <button class="rm-btn">↩ 복원</button>
        </div>
    `).join('');

    modal.innerHTML = `
        <div class="rm-header">
            <span class="rm-title">숨긴 세션 (${hiddenList.length}개)</span>
            <button class="rm-close">×</button>
        </div>
        <div class="rm-list">${items}</div>
        <div class="rm-footer">
            <button class="rm-all-btn">↩ 전체 복원</button>
        </div>
    `;

    overlay.classList.add('visible');
    modal.classList.add('visible');

    // 닫기
    modal.querySelector('.rm-close').onclick = closeRestoreModal;

    // 개별 복원
    modal.querySelectorAll('.rm-btn').forEach(btn => {
        btn.onclick = () => {
            restoreSession(parseInt(btn.closest('.rm-item').dataset.id));
            _lastSessionsJson = '';
            loadSessions();
            if (getHidden().size > 0) showRestoreModal();
            else closeRestoreModal();
        };
    });

    // 전체 복원
    modal.querySelector('.rm-all-btn').onclick = () => {
        restoreAll();
        _lastSessionsJson = '';
        loadSessions();
        closeRestoreModal();
    };
}

function closeRestoreModal() {
    const modal   = document.getElementById('restoreModal');
    const overlay = document.getElementById('restoreOverlay');
    if (modal)   modal.classList.remove('visible');
    if (overlay) overlay.classList.remove('visible');
}


// ── 우측 하단 플로팅 복원 버튼
function updateRestoreBtn(count) {
    let btn = document.getElementById('restoreBtn');
    if (!btn) {
        btn = document.createElement('div');
        btn.id = 'restoreBtn';
        document.body.appendChild(btn);
    }
    btn.onclick = showRestoreModal;   // onclick으로 중복 핸들러 방지
    if (count > 0) {
        btn.textContent = `↩  숨긴 세션 ${count}개`;
        btn.classList.add('visible');
    } else {
        btn.classList.remove('visible');
        closeRestoreModal();
    }
}


// ═══════════════════════════════════════════════════════════════
// 12. 사이드바
// ═══════════════════════════════════════════════════════════════
function buildSidebar(sessions) {
    const c = document.getElementById('sidebarSessions');
    c.innerHTML = '';

    sessions.slice(0, 50).forEach(s => {
        const item = document.createElement('div');
        item.className = 'sidebar-item';

        const info = document.createElement('div');
        info.className = 'sidebar-info';
        const kw = document.createElement('span'); kw.className='sidebar-keyword'; kw.textContent = s.summary||'···';
        const dt = document.createElement('span'); dt.className='sidebar-date';    dt.textContent = fmtDate(s.last_active_at||s.started_at);
        info.appendChild(kw); info.appendChild(dt);

        const del = document.createElement('button');
        del.className   = 'sidebar-del';
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


// ═══════════════════════════════════════════════════════════════
// 13. 초기화 + 자동 갱신
// ═══════════════════════════════════════════════════════════════

let _lastSessionsJson = '';

async function loadSessions() {
    try {
        const all     = await fetch(API_SESSIONS).then(r => r.json());
        _allSessions  = all;   // 모달 표시용 전체 캐시
        const hidden  = getHidden();
        const visible = all.filter(s => !hidden.has(s.session_id));
        const json    = JSON.stringify(visible);

        if (json !== _lastSessionsJson) {
            _lastSessionsJson = json;
            buildGraph(visible);
            buildSidebar(visible);
        }
    } catch(e) { console.error('세션 로드 실패', e); }
}

async function init() {
    initThree();
    bindEvents();
    startAnimation();
    await loadSessions();

    // ── 탭으로 돌아올 때 즉시 갱신 (채팅 후 복귀 시 최신 summary 반영)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') loadSessions();
    });

    // ── 60초마다 백그라운드 polling (새 세션·summary 자동 감지)
    setInterval(loadSessions, 60_000);
}

init();