const chatBox      = document.getElementById('chatBox');
const textInput    = document.getElementById('textInput');
const sendBtn      = document.getElementById('sendBtn');
const voiceBtn     = document.getElementById('voiceBtn');
const voiceStatus  = document.getElementById('voiceStatus');
const voiceBtnText = document.getElementById('voiceBtnText');

let sessionId     = null;
let mediaRecorder = null;
let isRecording   = false;


// ─────────────────────────────────────
// 1. 메시지 UI 추가
// ─────────────────────────────────────
function addMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
}


// ─────────────────────────────────────
// 2. 텍스트 채팅
// ─────────────────────────────────────
async function sendText() {
    const message = textInput.value.trim();
    if (!message) return;

    textInput.value = '';
    addMessage('user', message);
    setLoading(true);

    try {
        const res = await fetch('/api/v1/chat', {
            method : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body   : JSON.stringify({ session_id: sessionId, message }),
        });

        if (!res.ok) throw new Error(await res.text());

        const data = await res.json();
        sessionId  = data.session_id;
        addMessage('assistant', data.answer);

    } catch (e) {
        addMessage('assistant', '오류가 발생했습니다. 다시 시도해 주세요.');
        console.error(e);
    } finally {
        setLoading(false);
    }
}


// ─────────────────────────────────────
// 3. 음성 녹음 시작/종료
// ─────────────────────────────────────
async function toggleVoice() {
    if (isRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks = [];

        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => chunks.push(e.data);

        // ──────────────────────────────────────
        // 3-1. 녹음 완료 시 서버 전송
        // ──────────────────────────────────────
        mediaRecorder.onstop = async () => {
            const blob = new Blob(chunks, { type: mediaRecorder.mimeType });
            stream.getTracks().forEach(t => t.stop());
            await sendVoice(blob);
        };

        mediaRecorder.start();
        isRecording = true;
        voiceBtn.classList.add('recording');
        voiceBtnText.textContent = '⏹ 녹음 중지';
        voiceStatus.textContent  = '녹음 중...';

    } catch (e) {
        voiceStatus.textContent = '마이크 권한이 필요합니다.';
        console.error(e);
    }
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        voiceBtn.classList.remove('recording');
        voiceBtnText.textContent = '🎤 음성 입력';
        voiceStatus.textContent  = '처리 중...';
    }
}


// ─────────────────────────────────────
// 4. 음성 파일 서버 전송 + 재생
// ─────────────────────────────────────
async function sendVoice(blob) {
    setLoading(true);

    try {
        const ext  = blob.type.includes('webm') ? 'webm' : 'ogg';
        const form = new FormData();
        form.append('file', blob, `audio.${ext}`);
        if (sessionId) form.append('session_id', sessionId);

        const res = await fetch('/api/v1/voice', {
            method: 'POST',
            body  : form,
        });

        if (!res.ok) throw new Error(await res.text());

        const data = await res.json();

        // ──────────────────────────────────────
        // 4-1. 세션 ID + 텍스트 UI 표시
        // ──────────────────────────────────────
        if (data.session_id) sessionId = data.session_id;
        if (data.user_text)  addMessage('user',      data.user_text);
        if (data.answer)     addMessage('assistant', data.answer);

        // ──────────────────────────────────────
        // 4-2. base64 오디오 디코딩 + 재생
        // ──────────────────────────────────────
        if (data.audio_b64) {
            const binary  = atob(data.audio_b64);
            const bytes   = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            const audioBlob = new Blob([bytes], { type: 'audio/mpeg' });
            const audioUrl  = URL.createObjectURL(audioBlob);
            const audio     = new Audio(audioUrl);
            audio.onended   = () => URL.revokeObjectURL(audioUrl);
            await audio.play();
        }

    } catch (e) {
        addMessage('assistant', '오류가 발생했습니다. 다시 시도해 주세요.');
        console.error(e);
    } finally {
        setLoading(false);
        voiceStatus.textContent = '';
    }
}


// ─────────────────────────────────────
// 5. 로딩 상태
// ─────────────────────────────────────
function setLoading(loading) {
    sendBtn.disabled   = loading;
    voiceBtn.disabled  = loading;
    textInput.disabled = loading;
}


// ─────────────────────────────────────
// 6. 이벤트 바인딩
// ─────────────────────────────────────
sendBtn.addEventListener('click', sendText);
voiceBtn.addEventListener('click', toggleVoice);
textInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendText();
    }
});