'use strict';

const { app, BrowserWindow, ipcMain, session, screen, globalShortcut, desktopCapturer, shell } = require('electron');
const path = require('path');

require('dotenv').config({ path: path.join(__dirname, '.env') });

/**
 * ─────────────────────
 * 1. 상수
 * ─────────────────────
 */
const INTERNAL_TOKEN = process.env.INTERNAL_API_TOKEN || '';
const DEFAULT_BACKEND_URL = 'http://localhost:8000';

/**
 * BACKEND_URL에서 백엔드 origin을 파싱한다 (다기기: Tailscale 주소 지정 지점).
 * 값이 없거나 잘못된 형식이면 localhost 기본값으로 동작한다.
 * 
 * @returns {string} 백엔드 origin
 */
function resolveBackendOrigin() {
  try { return new URL(process.env.BACKEND_URL || DEFAULT_BACKEND_URL).origin; }
  catch { return DEFAULT_BACKEND_URL; }
}
const BACKEND_ORIGIN = resolveBackendOrigin();
const INJECT_ORIGIN = 'http://localhost';

// CSP — HTML meta 대신 여기서 주입
const CSP_CHAR = [
  `default-src 'self' ${BACKEND_ORIGIN}`,
  `script-src 'self' 'unsafe-inline' 'unsafe-eval'`,   // unsafe-eval: PixiJS 셰이더 컴파일 요구
  `style-src 'self' 'unsafe-inline'`,
  `img-src 'self' data: blob: ${BACKEND_ORIGIN}`,
  `connect-src 'self' ${BACKEND_ORIGIN}`,
  `media-src 'self' blob: data:`,
].join('; ');
const CSP_SESSION = [
  `default-src 'self' ${BACKEND_ORIGIN}`,
  `script-src 'self' 'unsafe-inline'`,
  `style-src 'self' 'unsafe-inline'`,
  `img-src 'self' data: blob: ${BACKEND_ORIGIN}`,   // 이미지 첨부 미리보기(blob)·썸네일(data) 허용
  `connect-src 'self' ${BACKEND_ORIGIN}`,
].join('; ');
const SESSION_PAGE = 'session.html';
const FILE_SCHEME = 'file://';
const HEADER_CSP = 'Content-Security-Policy';
const HEADER_ORIGIN = 'Origin';
const HEADER_TOKEN = 'X-Internal-Token';
const SHORTCUT_VOICE = 'F9';
const SOURCE_SCREEN = 'screen';
const ON_TOP_LEVEL = 'screen-saver';   // alwaysOnTop 최상위 레벨 (다른 창 클릭에도 위 유지)

// 캐릭터 창 크기·화면 우하단 오프셋
const CHAR_W = 400;
const CHAR_H = 700;
const CHAR_MARGIN_X = 420;

// 세션 창 크기·캐릭터 기준 오프셋
const SESSION_W = 380;
const SESSION_H = 640;
const SESSION_OFFSET_X = 390;
const SESSION_OFFSET_Y = 40;

// IPC 채널
const CH = Object.freeze({
  MOVE_WINDOW       : 'move-window',
  CLOSE_WINDOW      : 'close-window',
  SET_IGNORE_MOUSE  : 'set-ignore-mouse',
  GET_BOUNDS        : 'get-bounds',
  TOGGLE_SESSION_WIN: 'toggle-session-win',
  GET_SCREEN_SOURCE : 'get-screen-source',
  GET_SCREEN_SIZE   : 'get-screen-size',
  SWITCH_SESSION    : 'switch-session',
  NEW_SESSION       : 'new-session',
  CHAT_TEXT         : 'chat-text',
  MIC_TOGGLE        : 'mic-toggle',
  VOICE_TOGGLE      : 'voice-toggle',
  SET_WIN_SIZE      : 'set-win-size',
  REFRESH_SESSIONS  : 'refresh-sessions',
  GET_BACKEND_URL   : 'get-backend-url',
  OPEN_EXTERNAL     : 'open-external',
});

const WEB_PREFERENCES = {
  preload         : path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  nodeIntegration : false,
  sandbox         : false,
};

let win = null;         // 캐릭터창
let sessionWin = null;  // 통합 채팅 패널 (세션 목록 + 대화 기록 + 텍스트 입력)

/**
 * 렌더러의 외부 네비게이션·새 창 생성을 차단한다.
 * 앱은 loadFile 로컬 페이지만 쓰고 창은 IPC로만 여므로 전부 거부해도 안전.
 * 
 * @param {Electron.WebContents} wc
 * @returns {void}
 */
function hardenWebContents(wc) {
  wc.setWindowOpenHandler(() => ({ action: 'deny' }));
  wc.on('will-navigate', (e) => e.preventDefault());
}

/**
 * ─────────────────────
 * 2. 캐릭터 창
 * ─────────────────────
 */
function createCharWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  win = new BrowserWindow({
    width      : CHAR_W,
    height     : CHAR_H,
    x          : width - CHAR_MARGIN_X,
    y          : height - CHAR_H,
    transparent: true,
    frame      : false,
    alwaysOnTop: true,
    skipTaskbar: false,   // 작업표시줄 아이콘 표시
    resizable  : false,
    webPreferences: WEB_PREFERENCES,
  });

  hardenWebContents(win.webContents);
  win.setAlwaysOnTop(true, ON_TOP_LEVEL);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  win.on('blur', () => {
    if (!win.isDestroyed()) win.setAlwaysOnTop(true, ON_TOP_LEVEL);
  });
}

/**
 * ─────────────────────
 * 3. 앱 시작 / 보안
 * ─────────────────────
 */
(async () => {
  await app.whenReady();

  // 3-1. Origin 고정 + PSK 토큰 주입
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    let isBackend = false;
    try { isBackend = new URL(details.url).origin === BACKEND_ORIGIN; } catch {}
    if (isBackend) {
      details.requestHeaders[HEADER_ORIGIN] = INJECT_ORIGIN;
      details.requestHeaders[HEADER_TOKEN] = INTERNAL_TOKEN;
    }
    callback({ requestHeaders: details.requestHeaders });
  });

  // 3-2. CSP 주입 — 로컬 페이지(file://)의 메인 프레임에 창별 CSP 헤더 부여.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.resourceType === 'mainFrame' && details.url.startsWith(FILE_SCHEME)) {
      const csp = details.url.endsWith(SESSION_PAGE) ? CSP_SESSION : CSP_CHAR;
      callback({ responseHeaders: { ...details.responseHeaders, [HEADER_CSP]: [csp] } });
      return;
    }
    callback({ responseHeaders: details.responseHeaders });
  });

  createCharWindow();

  // 3-3. F9 글로벌 단축키 → 음성 토글 (캐릭터창 + 패널 마이크 상태 동기화)
  globalShortcut.register(SHORTCUT_VOICE, () => {
    if (win        && !win.isDestroyed())        win.webContents.send(CH.VOICE_TOGGLE);
    if (sessionWin && !sessionWin.isDestroyed()) sessionWin.webContents.send(CH.VOICE_TOGGLE);
  });
})();

app.on('will-quit',         () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => app.quit());

/**
 * ─────────────────────
 * 4. IPC — 창 제어
 * ─────────────────────
 */
ipcMain.on(CH.MOVE_WINDOW, (event, { x, y }) => {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;   // 렌더러 입력 검증
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w) w.setPosition(Math.round(x), Math.round(y));
});

ipcMain.on(CH.CLOSE_WINDOW, (event) => {
  const sender = event.sender;
  if (sessionWin && !sessionWin.isDestroyed() && sender === sessionWin.webContents) {
    sessionWin.close();
  } else {
    app.quit();
  }
});

ipcMain.on(CH.SET_IGNORE_MOUSE, (event, ignore) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  if (w) w.setIgnoreMouseEvents(ignore, { forward: true });
});

ipcMain.handle(CH.GET_BOUNDS, (event) => {
  const w = BrowserWindow.fromWebContents(event.sender);
  return w ? w.getBounds() : null;
});

// 백엔드 origin 조회 — preload가 동기 요청
ipcMain.on(CH.GET_BACKEND_URL, (event) => {
  event.returnValue = BACKEND_ORIGIN;
});

// 외부 URL 열기 — 검색 결과 등을 이 기기의 기본 브라우저로.
ipcMain.on(CH.OPEN_EXTERNAL, (_, url) => {
  try {
    const u = new URL(String(url));
    if (u.protocol === 'http:' || u.protocol === 'https:') shell.openExternal(u.href);
  } catch {}
});

// 화면 인식용 — 주 화면 소스 id 반환
ipcMain.handle(CH.GET_SCREEN_SOURCE, async () => {
  const sources = await desktopCapturer.getSources({ types: [SOURCE_SCREEN] });
  const src = sources[0];
  console.log('[main] screen source provided:', src ? src.id : 'none');
  return src ? src.id : null;
});

// 자율 이동용 — 주 화면(캡처 대상)의 전체 경계 + 작업영역 반환
ipcMain.handle(CH.GET_SCREEN_SIZE, () => {
  const d = screen.getPrimaryDisplay();
  return { bounds: d.bounds, workArea: d.workArea };
});

/**
 * ─────────────────────
 * 5. IPC — 세션 패널
 * ─────────────────────
 */
ipcMain.on(CH.TOGGLE_SESSION_WIN, () => {
  if (sessionWin && !sessionWin.isDestroyed()) {
    sessionWin.close();
    return;
  }
  const b = win.getBounds();
  sessionWin = new BrowserWindow({
    width      : SESSION_W,
    height     : SESSION_H,
    x          : b.x - SESSION_OFFSET_X,
    y          : b.y + SESSION_OFFSET_Y,
    frame      : false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: WEB_PREFERENCES,
  });
  hardenWebContents(sessionWin.webContents);
  sessionWin.setAlwaysOnTop(true, ON_TOP_LEVEL);
  sessionWin.loadFile(path.join(__dirname, 'renderer', 'session.html'));
  sessionWin.on('closed', () => { sessionWin = null; });
});

// 세션 전환 / 새 세션 / 텍스트 / 마이크 — sessionWin → 캐릭터창
ipcMain.on(CH.SWITCH_SESSION, (_, id) => {
  if (win && !win.isDestroyed()) win.webContents.send(CH.SWITCH_SESSION, id);
});

ipcMain.on(CH.NEW_SESSION, () => {
  if (win && !win.isDestroyed()) win.webContents.send(CH.SWITCH_SESSION, null);
});

ipcMain.on(CH.CHAT_TEXT, (_, text) => {
  if (win && !win.isDestroyed()) win.webContents.send(CH.CHAT_TEXT, text);
});

ipcMain.on(CH.MIC_TOGGLE, () => {
  if (win && !win.isDestroyed()) win.webContents.send(CH.VOICE_TOGGLE);
});

// 창 크기 조절 (sessionWin 최소화/복원)
ipcMain.on(CH.SET_WIN_SIZE, (_, { w, h }) => {
  if (!Number.isFinite(w) || !Number.isFinite(h)) return;   // 렌더러 입력 검증
  if (sessionWin && !sessionWin.isDestroyed()) sessionWin.setSize(Math.round(w), Math.round(h));
});

// 새 세션 생성 알림 (캐릭터창 → sessionWin)
ipcMain.on(CH.REFRESH_SESSIONS, () => {
  if (sessionWin && !sessionWin.isDestroyed()) sessionWin.webContents.send(CH.REFRESH_SESSIONS);
});