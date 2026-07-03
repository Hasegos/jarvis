'use strict';

/**
 * @file 이미지 첨부 모듈 — 파일 선택/붙여넣기 → 리사이즈(JPEG) → 다중 미리보기 → 전송용 b64 제공.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.attach = (() => {
  const MAX_DIM = 1280;
  const MAX_COUNT = 4;           // 백엔드 images_b64 최대 장수
  const JPEG_MIME = 'image/jpeg';
  const JPEG_QUALITY = 0.8;
  const MSG_FAIL = '이미지를 불러올 수 없습니다.';
  const MSG_LIMIT = `이미지는 최대 ${MAX_COUNT}장까지 첨부할 수 있습니다.`;
  const REMOVE_ICON = '✕';
  const REMOVE_TITLE = '첨부 취소';

  /** @constant {Readonly<Object>} 동적 생성 요소 클래스명 */
  const CLASS = Object.freeze({
    item      : 'attach-preview__item',
    itemImg   : 'attach-preview__img',
    itemRemove: 'attach-preview__remove',
    hidden    : 'hidden',
  });

  /** @type {Array<{dataUrl: string}>} 전송 대기 이미지 목록 */
  let pending = [];

  /**
   * 파일을 Image 요소로 로드한다.
   * 
   * @param {File} file - 선택된 이미지 파일
   * @returns {Promise<HTMLImageElement>}
   */
  function _loadImage(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
      img.src = url;
    });
  }

  /**
   * 이미지를 최대변 기준으로 축소해 JPEG data URL로 변환한다.
   * 
   * @param {HTMLImageElement} img - 로드된 이미지
   * @returns {string} data URL
   */
  function _resize(img) {
    const ratio = Math.min(MAX_DIM / img.width, MAX_DIM / img.height, 1);
    const w = Math.round(img.width * ratio);
    const h = Math.round(img.height * ratio);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
    return canvas.toDataURL(JPEG_MIME, JPEG_QUALITY);
  }

  /**
   * 미리보기 스트립을 현재 목록으로 다시 그린다.
   * 
   * @returns {void}
   */
  function _render() {
    const { ui } = JarvisWeb;
    const box = ui.el.attachPreview;
    box.replaceChildren();
    pending.forEach((item, idx) => {
      const wrap = document.createElement('div');
      wrap.className = CLASS.item;

      const img = document.createElement('img');
      img.className = CLASS.itemImg;
      img.src = item.dataUrl;
      img.alt = `첨부 이미지 ${idx + 1}`;
      img.addEventListener('click', () => ui.openViewer(item.dataUrl));

      const del = document.createElement('button');
      del.className = CLASS.itemRemove;
      del.title = REMOVE_TITLE;
      del.textContent = REMOVE_ICON;
      del.addEventListener('click', () => removeAt(idx));

      wrap.append(img, del);
      box.appendChild(wrap);
    });
    box.classList.toggle(CLASS.hidden, pending.length === 0);
  }

  /**
   * 선택/붙여넣기된 파일들을 첨부 목록에 추가한다 (리사이즈 + 미리보기).
   * 
   * @param {FileList|File[]} files - 이미지 파일들
   * @returns {Promise<void>}
   */
  async function addFiles(files) {
    const { ui } = JarvisWeb;
    for (const file of [...files]) {
      if (!file || !file.type.startsWith('image/')) continue;
      if (pending.length >= MAX_COUNT) {
        ui.addMsg(ui.ROLE.STATUS, MSG_LIMIT);
        break;
      }
      try {
        pending.push({ dataUrl: _resize(await _loadImage(file)) });
      } catch (e) {
        console.warn('[web/attach] 이미지 처리 실패:', e);
        ui.addMsg(ui.ROLE.STATUS, MSG_FAIL);
      }
    }
    _render();
  }

  /**
   * 지정 인덱스의 첨부를 제거한다.
   * 
   * @param {number} idx - 목록 인덱스
   * @returns {void}
   */
  function removeAt(idx) {
    pending.splice(idx, 1);
    _render();
  }

  /**
   * 파일 선택 대화상자를 연다 (📎 버튼).
   * 
   * @returns {void}
   */
  function pick() {
    JarvisWeb.ui.el.attachInput.click();
  }

  /**
   * 첨부 전체를 해제한다.
   * 
   * @returns {void}
   */
  function clear() {
    pending = [];
    JarvisWeb.ui.el.attachInput.value = '';
    _render();
  }

  /**
   * 전송 대기 중인 첨부 목록을 반환한다.
   * 
   * @returns {Array<{dataUrl: string}>}
   */
  function get() {
    return pending;
  }

  return { pick, addFiles, removeAt, clear, get };
})();