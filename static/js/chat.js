// ═══════════════════════════════════════════════════════════════
// 1. 세션 ID — URL ?id= 파라미터에서 읽기
// ═══════════════════════════════════════════════════════════════
const params = new URLSearchParams(window.location.search);
const rawId  = params.get('id');
let currentSessionId = (rawId && rawId !== 'new') ? parseInt(rawId) : null;


// ═══════════════════════════════════════════════════════════════
// 2. API 상수
// ═══════════════════════════════════════════════════════════════
const API = {
    chat    : '/api/v1/chat',
    voice   : '/api/v1/voice',
    messages: (id) => `/api/v1/chat/sessions/${id}/messages`,
    sessions: '/api/v1/chat/sessions',
};


// ═══════════════════════════════════════════════════════════════
// 3. 세션 로드 (기존 세션이면 메시지 복원)
// ═══════════════════════════════════════════════════════════════
async function loadSession() {
    if (!currentSessionId) {
        document.getElementById('chatSessionLabel').textContent = 'NEW SESSION';
        return;
    }

    document.getElementById('chatSessionLabel').textContent = `SESSION #${currentSessionId}`;

    try {
        const [messages, sessions] = await Promise.all([
            fetch(API.messages(currentSessionId)).then(r => r.json()),
            fetch(API.sessions).then(r => r.json()),
        ]);

        messages.forEach(m => addMessage(m.role, m.content));

        const s = sessions.find(s => s.session_id === currentSessionId);
        if (s?.summary) {
            document.getElementById('chatSessionLabel').textContent = `${s.summary} · #${currentSessionId}`;
        }
    } catch (e) {
        console.error('세션 복원 실패', e);
    }
}


// ═══════════════════════════════════════════════════════════════
// 4. 채팅 UI
// ═══════════════════════════════════════════════════════════════
function addMessage(role, text) {
    const chatBox = document.getElementById('chatBox');
    const div     = document.createElement('div');
    div.className   = `message ${role}`;
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function setLoading(loading) {
    document.getElementById('sendBtn').disabled   = loading;
    document.getElementById('voiceBtn').disabled  = loading;
    document.getElementById('textInput').disabled = loading;
}

// ──────────────────────────────────────
// 4-1. 세션 ID 갱신 (새 세션 생성 시)
// ──────────────────────────────────────
function updateSessionId(newId) {
    if (!newId || newId === currentSessionId) return;
    currentSessionId = newId;
    history.replaceState(null, '', `/chat?id=${newId}`);
    document.getElementById('chatSessionLabel').textContent = `SESSION #${newId}`;
}


// ═══════════════════════════════════════════════════════════════
// 5. 텍스트 전송
// ═══════════════════════════════════════════════════════════════
async function sendText() {
    const input   = document.getElementById('textInput');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    addMessage('user', message);
    setLoading(true);

    try {
        const res = await fetch(API.chat, {
            method : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body   : JSON.stringify({ session_id: currentSessionId, message }),
        });
        if (!res.ok) throw new Error(await res.text());

        const data = await res.json();
        updateSessionId(data.session_id);
        addMessage('assistant', data.answer);
        if (data.audio_b64) await playAudio(data.audio_b64);

    } catch (e) {
        addMessage('assistant', '오류가 발생했습니다. 다시 시도해 주세요.');
        console.error(e);
    } finally {
        setLoading(false);
    }
}


// ═══════════════════════════════════════════════════════════════
// 6. 음성 녹음
// ═══════════════════════════════════════════════════════════════
let mediaRecorder = null;
let isRecording   = false;

async function toggleVoice() {
    if (isRecording) stopRecording();
    else             await startRecording();
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => chunks.push(e.data);

        // ──────────────────────────────────────
        // 6-1. 녹음 완료 → 서버 전송
        // ──────────────────────────────────────
        mediaRecorder.onstop = async () => {
            const blob = new Blob(chunks, { type: mediaRecorder.mimeType });
            stream.getTracks().forEach(t => t.stop());
            await sendVoice(blob);
        };

        mediaRecorder.start();
        isRecording = true;
        document.getElementById('voiceBtn').classList.add('recording');
        document.getElementById('voiceBtnText').textContent = '⏹ 녹음 중지';
        document.getElementById('voiceStatus').textContent  = '녹음 중...';
    } catch (e) {
        document.getElementById('voiceStatus').textContent = '마이크 권한이 필요합니다.';
        console.error(e);
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        document.getElementById('voiceBtn').classList.remove('recording');
        document.getElementById('voiceBtnText').textContent = '🎤 음성 입력';
        document.getElementById('voiceStatus').textContent  = '처리 중...';
    }
}

async function sendVoice(blob) {
    setLoading(true);
    try {
        const ext  = blob.type.includes('webm') ? 'webm' : 'ogg';
        const form = new FormData();
        form.append('file', blob, `audio.${ext}`);
        if (currentSessionId) form.append('session_id', String(currentSessionId));

        const res = await fetch(API.voice, { method: 'POST', body: form });
        if (!res.ok) throw new Error(await res.text());

        const data = await res.json();
        updateSessionId(data.session_id);
        if (data.user_text) addMessage('user',      data.user_text);
        if (data.answer)    addMessage('assistant', data.answer);
        if (data.audio_b64) await playAudio(data.audio_b64);

    } catch (e) {
        addMessage('assistant', '오류가 발생했습니다. 다시 시도해 주세요.');
        console.error(e);
    } finally {
        setLoading(false);
        document.getElementById('voiceStatus').textContent = '';
    }
}


// ═══════════════════════════════════════════════════════════════
// 7. 오디오 재생
// ═══════════════════════════════════════════════════════════════
async function playAudio(b64) {
    const bytes = new Uint8Array(atob(b64).split('').map(c => c.charCodeAt(0)));
    const url   = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
}


// ═══════════════════════════════════════════════════════════════
// 8. 이벤트 바인딩
// ═══════════════════════════════════════════════════════════════
document.getElementById('sendBtn').addEventListener('click', sendText);
document.getElementById('voiceBtn').addEventListener('click', toggleVoice);
document.getElementById('textInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); }
});


// ═══════════════════════════════════════════════════════════════
// 9. 초기화
// ═══════════════════════════════════════════════════════════════
loadSession();
document.getElementById('textInput').focus();