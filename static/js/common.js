/**
 * 전역 공유 유틸리티
 */
'use strict';

/**
 * 1. API 엔드포인트 상수
 */
const API_ENDPOINTS = Object.freeze({
  chat    : '/api/v1/chat',
  voice   : '/api/v1/voice',
  sessions: '/api/v1/chat/sessions',
  messages: id => `/api/v1/chat/sessions/${id}/messages`,
});

/**
 * 2. 날짜 유틸리티
 */

/**
 * 날짜 문자열을 Date 객체로 파싱합니다.
 * UTC 접미사(Z)가 없으면 자동으로 추가합니다.
 * 
 * @param {string|null} d - ISO 8601 날짜 문자열
 * @returns {Date|null} 파싱된 Date, 입력이 falsy 이면 null
 */
function parseDate(d) {
  if (!d) return null;
  return new Date(d.endsWith('Z') ? d : d + 'Z');
}

/**
 * 주어진 날짜로부터 현재까지 경과된 시간을 시(hour) 단위로 반환합니다.
 * 
 * @param {string|null} d - ISO 8601 날짜 문자열
 * @returns {number} 경과 시간(h). 파싱 실패 시 9999 반환
 */
function ageHours(d) {
  const dt = parseDate(d);
  return dt ? (Date.now() - dt.getTime()) / 3_600_000 : 9999;
}

/**
 * 날짜 문자열을 'MM-DD HH:mm' 형식으로 포맷합니다.
 * 
 * @param {string|null} d - ISO 8601 날짜 문자열
 * @returns {string} 포맷된 문자열. 파싱 실패 시 '---'
 */
function fmtDate(d) {
  const dt = parseDate(d);
  if (!dt) return '---';
  const p = n => String(n).padStart(2, '0');
  return `${p(dt.getMonth() + 1)}-${p(dt.getDate())} ${p(dt.getHours())}:${p(dt.getMinutes())}`;
}

/**
 * 3. API 호출 공통 래퍼
 */

/**
 * API 에러 (HTTP 비정상 응답)
 * 
 * @param {number} status
 * @param {string} body
 */
class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}: ${body}`);
    this.name   = 'ApiError';
    this.status = status;
    this.body   = body;
  }
}

/**
 * fetch 래퍼 — 오류 처리 표준화
 *
 * - Content-Type: application/json 자동 설정 (FormData 제외)
 * - !res.ok → ApiError throw
 * - JSON 파싱 실패 → 원본 텍스트로 에러 throw
 *
 * @param {string}  url
 * @param {RequestInit} [options]
 * @returns {Promise<any>} 파싱된 JSON
 */
async function apiFetch(url, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
  });

  const text = await res.text();

  if (!res.ok) {
    throw new ApiError(res.status, text);
  }

  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`JSON 파싱 실패: ${text}`);
  }
}