'use strict';

const { contextBridge, ipcRenderer } = require('electron');

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

const API_NAME = 'electronAPI';

contextBridge.exposeInMainWorld(API_NAME, {
  // 백엔드 origin
  backendUrl: ipcRenderer.sendSync(CH.GET_BACKEND_URL),

  // 외부 URL을 이 기기의 기본 브라우저로 열기 (http/https만 허용)
  openExternal: (url) => ipcRenderer.send(CH.OPEN_EXTERNAL, url),

  // 창 제어
  moveWindow    : (x, y) => ipcRenderer.send(CH.MOVE_WINDOW, { x, y }),
  closeWindow   : ()     => ipcRenderer.send(CH.CLOSE_WINDOW),
  getBounds     : ()     => ipcRenderer.invoke(CH.GET_BOUNDS),
  setIgnoreMouse: (v)    => ipcRenderer.send(CH.SET_IGNORE_MOUSE, v),

  // 음성 토글 수신 (캐릭터창·세션창)
  onVoiceToggle: (cb) => ipcRenderer.on(CH.VOICE_TOGGLE, () => cb()),

  // 세션창 토글 (캐릭터창 → main)
  toggleSessionWin: () => ipcRenderer.send(CH.TOGGLE_SESSION_WIN),

  // 주 화면 소스 id 조회 (화면 인식용)
  getScreenSource: () => ipcRenderer.invoke(CH.GET_SCREEN_SOURCE),

  // 주 화면 작업영역 조회 (자율 이동용)
  getScreenSize: () => ipcRenderer.invoke(CH.GET_SCREEN_SIZE),

  // 세션 전환 (sessionWin → main → 캐릭터창)
  switchSession  : (id) => ipcRenderer.send(CH.SWITCH_SESSION, id),
  newSession     : ()   => ipcRenderer.send(CH.NEW_SESSION),
  onSwitchSession: (cb) => ipcRenderer.on(CH.SWITCH_SESSION, (_, id) => cb(id)),

  // 텍스트(+선택 이미지들) 전송 (세션창 → main → 캐릭터창)
  sendChatText: (text, imagesB64 = []) => ipcRenderer.send(CH.CHAT_TEXT, { text, images_b64: imagesB64 || [] }),
  onChatText  : (cb) => ipcRenderer.on(CH.CHAT_TEXT, (_, payload) => cb(payload)),

  // 마이크 (세션창 → main → 캐릭터창)
  micToggle: () => ipcRenderer.send(CH.MIC_TOGGLE),

  // 창 크기 조절 (sessionWin 최소화/복원)
  setWinSize: (w, h) => ipcRenderer.send(CH.SET_WIN_SIZE, { w, h }),

  // 새 세션 생성 알림 (캐릭터창 → main → sessionWin)
  refreshSessions  : ()   => ipcRenderer.send(CH.REFRESH_SESSIONS),
  onRefreshSessions: (cb) => ipcRenderer.on(CH.REFRESH_SESSIONS, () => cb()),
});