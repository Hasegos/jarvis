/**
 * JARVIS 홀로그램 — 앱 초기화
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  /**
   * 1. 상수
   */
  J.const = {
    PARTICLE_COUNT: 1500,
    STAR_COUNT: 100,
    BEAM_COUNT: 10,
    SPHERE_R: 2.6,
    GREETING: '어서오세요, 아이언 님. 무엇을 도와드릴까요?',
    INPUT_MAX_H: 120,
    HIDDEN_KEY: 'jarvis_hidden_sessions',
    FRAME_MS: 1000 / 30,
  };

  /**
   * 2. 런타임 상태
   *
   * 재할당되는 primitive는 여기에 두어야 모듈 간 공유된다.
   */
  J.state = {
    currentSessionId: null,
    panelMode: 'collapsed',
    panelHidden: false,
    sphereState: 'idle',
    busy: false,
    bootDone: false,
    currentAudio: null,
    mediaRecorder: null,
    isRecording: false,
    recChunks: [],
    toolColor: null,
  };

  /**
   * Three.js 부팅 공유 상태
   *
   * scene.js와 boot.js가 공유하는 파티클 수렴 진행 상태.
   */
  J.three = { booting: false, bootProgress: 0 };

  /**
   * 3. DOM 캐시
   *
   * DOMContentLoaded 후 initDom()에서 한 번 수집한다.
   */
  J.dom = {};
  function initDom() {
    const d = J.dom;
    d.boot       = document.getElementById('boot');
    d.bootTitle  = document.getElementById('bootTitle');
    d.bootStatus = document.getElementById('bootStatus');
    d.orbState   = document.getElementById('orbState');
    d.recIndicator = document.getElementById('recIndicator');
    d.fab        = document.getElementById('hudFab');
    d.fabDot     = document.getElementById('hudFabDot');
    d.hudPanel   = document.getElementById('hudPanel');
    d.messages   = document.getElementById('hudMessages');
    d.sessions   = document.getElementById('hudSessions');
    d.sessionList = document.getElementById('sessionList');
    d.hiddenList = document.getElementById('hiddenList');
    d.textInput  = document.getElementById('textInput');
    d.btnSend    = document.getElementById('btnSend');
    d.btnExpand  = document.getElementById('btnExpand');
    d.btnNew     = document.getElementById('btnNew');
    d.btnSessions = document.getElementById('btnSessions');
    d.btnHide    = document.getElementById('btnHide');
    d.btnBack    = document.getElementById('btnBack');
  }

  /**
   * 4. 이벤트 바인딩
   *
   * 채팅 입력(Enter/Shift+Enter), 패널 버튼, 부팅 클릭, F9 음성 단축키를 등록한다.
   */
  function bindEvents() {
    const d = J.dom;
    d.btnSend.addEventListener('click', J.sendText);
    d.textInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); J.sendText(); }
    });
    d.textInput.addEventListener('input', J.autoResizeInput);
    d.btnExpand.addEventListener('click', J.toggleExpand);
    d.btnNew.addEventListener('click', J.newSession);
    d.btnSessions.addEventListener('click', J.openSessions);
    d.btnHide.addEventListener('click', J.hidePanel);
    d.btnBack.addEventListener('click', () => J.setPanelMode('collapsed'));
    d.fab.addEventListener('click', J.showPanel);

    // 부팅 시작
    d.boot.addEventListener('click', J.startBoot, { once: true });

    // 단축키: F9 음성
    document.addEventListener('keydown', e => {
      if (e.key === 'F9') {
        e.preventDefault();
        if (J.state.bootDone) J.toggleVoice();
      }
    });
  }

  /**
   * 5. 초기화
   *
   * DOM 수집 → Three.js 씬 구성 → 이벤트 바인딩.
   */
  function init() {
    initDom();
    J.initScene();
    bindEvents();
  }

  document.addEventListener('DOMContentLoaded', init);

})(window.JARVIS);