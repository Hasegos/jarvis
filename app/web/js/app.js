'use strict';

/**
 * @file 부트스트랩 — 토큰 게이트·이벤트 배선. 모든 모듈 로드 후 실행.
 */
(() => {
  const { dom, ui, api, chat, voice, sessions, attach } = JarvisWeb;
  const el = ui.el;
  const KEY_ENTER = 'Enter';

  const scope = dom.createScope();

  /**
   * 토큰을 검증(/chat/sessions 호출)하고 통과하면 앱을 연다.
   * 
   * @returns {Promise<void>}
   */
  async function enter() {
    const input = el.gateToken.value.trim();
    if (input) api.setToken(input);
    try {
      const res = await fetch(`${api.BASE}/chat/sessions`, { headers: api.headers(false) });
      if (res.status === 401) { ui.showGate(true); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      ui.showApp();
    } catch (e) {
      console.warn('[web/app] 접속 실패:', e);
      ui.showGate(true, '서버에 연결할 수 없습니다.');   // 토큰 오류와 구분
    }
  }

  /**
   * 입력창 텍스트(+첨부 이미지)를 전송하고 입력 상태를 비운다.
   * 
   * @returns {void}
   */
  function handleSend() {
    const text = el.input.value.trim();
    const images = attach.get();
    if (!text && !images.length) return;
    el.input.value = '';
    el.input.style.height = '';
    chat.send(text, [...images]);   // clear 전에 복사
    attach.clear();
  }

  /**
   * 세션 드로어를 연다 (목록 갱신 포함).
   * 
   * @returns {Promise<void>}
   */
  async function openDrawer() {
    await sessions.load();
    ui.openDrawer();
  }

  // ── 게이트 ──
  scope.on(el.gateSubmit, 'click', enter);
  scope.on(el.gateToken, 'keydown', (e) => {
    if (e.key === KEY_ENTER) enter();
  });

  // ── 입력바 ──
  scope.on(el.btnSend, 'click', handleSend);
  scope.on(el.input, 'keydown', (e) => {
    if (e.key === KEY_ENTER && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });
  // textarea 자동 높이
  scope.on(el.input, 'input', (e) => {
    e.target.style.height = '';
    e.target.style.height = `${e.target.scrollHeight}px`;
  });
  scope.on(el.btnMic, 'click', voice.toggle);

  // ── 이미지 첨부 (📎 다중 선택 / 붙여넣기 / 항목별 취소는 attach가 처리) ──
  scope.on(el.btnAttach, 'click', attach.pick);
  scope.on(el.attachInput, 'change', (e) => {
    if (e.target.files?.length) attach.addFiles(e.target.files);
  });
  scope.on(el.input, 'paste', (e) => {
    const files = [...(e.clipboardData?.items || [])]
      .filter((i) => i.type.startsWith('image/'))
      .map((i) => i.getAsFile());
    if (files.length) { e.preventDefault(); attach.addFiles(files); }
  });

  // ── 이미지 확대 뷰어: 채팅 썸네일 클릭으로 열고, 아무 곳이나 탭하면 닫힘 ──
  scope.on(el.chat, 'click', (e) => {
    const img = e.target.closest('.msg__img');
    if (img) ui.openViewer(img.src);
  });
  scope.on(el.viewer, 'click', ui.closeViewer);

  // ── confirm ──
  scope.on(el.btnApprove, 'click', () => chat.resolveConfirm(true));
  scope.on(el.btnReject, 'click', () => chat.resolveConfirm(false));

  // ── 세션 드로어 ──
  scope.on(el.btnDrawer, 'click', openDrawer);
  scope.on(el.btnDrawerClose, 'click', ui.closeDrawer);
  scope.on(el.drawerBackdrop, 'click', ui.closeDrawer);
  scope.on(el.btnNew, 'click', sessions.startNew);

  // 세션 목록: 이벤트 위임
  scope.on(el.sessionList, 'click', async (e) => {
    const item = e.target.closest(`.${sessions.CLASS.item}`);
    if (!item) return;
    const id = Number(item.dataset.id);
    if (e.target.closest(`.${sessions.CLASS.itemDelete}`)) {
      await sessions.remove(id);
      return;
    }
    ui.closeDrawer();
    await sessions.open(id);
  });

  // ── 부트스트랩: 저장된 토큰 있으면 자동 진입 ──
  if (api.getToken()) enter();
  else ui.showGate(false);
})();