'use strict';

/**
 * @file API 유틸 — 토큰 보관·공통 헤더·오디오 재생.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.api = (() => {
  const BASE = '/api/v1';
  const TOKEN_KEY = 'jarvis_token';
  const HEADER_TOKEN = 'X-Internal-Token';
  const HEADER_JSON = 'Content-Type';
  const MIME_JSON = 'application/json';
  const AUDIO_DATA_PREFIX = 'data:';
  const MP3_DATA_URI = 'data:audio/mp3;base64,';

  let currentAudio = null;

  /**
   * 저장된 내부 토큰을 반환한다.
   * 
   * @returns {string}
   */
  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  /**
   * 내부 토큰을 저장한다.
   * 
   * @param {string} token - X-Internal-Token 값
   * @returns {void}
   */
  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  /**
   * 토큰 포함 공통 요청 헤더를 만든다.
   * 
   * @param {boolean} [json] - JSON 바디 여부
   * @returns {Object}
   */
  function headers(json = true) {
    const h = { [HEADER_TOKEN]: getToken() };
    if (json) h[HEADER_JSON] = MIME_JSON;
    return h;
  }

  /**
   * base64 오디오를 재생한다.
   * 
   * @param {string} b64 - mp3 base64 또는 data URI
   * @returns {void}
   */
  function playAudio(b64) {
    if (!b64 || typeof b64 !== 'string') return;
    if (currentAudio) {
      try { currentAudio.pause(); } catch {}
      currentAudio.src = '';
    }
    const audio = new Audio(b64.startsWith(AUDIO_DATA_PREFIX) ? b64 : `${MP3_DATA_URI}${b64}`);
    audio.addEventListener('ended', () => {
      audio.src = '';
      if (currentAudio === audio) currentAudio = null;
    }, { once: true });
    currentAudio = audio;
    audio.play().catch(() => {
      audio.src = '';
      if (currentAudio === audio) currentAudio = null;
    });
  }

  return { BASE, getToken, setToken, headers, playAudio };
})();