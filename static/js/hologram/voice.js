/**
 * JARVIS 홀로그램 — 음성
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  /**
   * 마이크 녹음 시작
   *
   * MediaRecorder를 생성하고 녹음을 시작한다.
   * 녹음 종료(onstop) 시 sendVoice()를 자동 호출한다.
   *
   * @returns {Promise<void>} 마이크 접근 성공 시 resolve
   */
  function startRecording() {
    return navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      J.state.recChunks = [];
      const rec = new MediaRecorder(stream);
      J.state.mediaRecorder = rec;
      rec.ondataavailable = e => { if (e.data.size) J.state.recChunks.push(e.data); };
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(J.state.recChunks, { type: rec.mimeType || 'audio/webm' });
        J.sendVoice(blob);
      };
      rec.start();
      J.state.isRecording = true;
      J.dom.recIndicator.hidden = false;
      J.setSphereState('recording');
    }).catch(e => {
      console.error('마이크 접근 실패', e);
      J.setSphereState('idle');
    });
  }

  /**
   * 마이크 녹음 중지
   *
   * MediaRecorder.stop()을 호출하면 onstop 콜백에서 sendVoice()가 이어진다.
   */
  function stopRecording() {
    const rec = J.state.mediaRecorder;
    if (!rec || !J.state.isRecording) return;
    J.state.isRecording = false;
    J.dom.recIndicator.hidden = true;
    rec.stop();
    J.setSphereState('idle');
  }

  /**
   * 1. 음성 토글 (F9)
   *
   * 녹음 중이면 중지, 아니면 시작. busy 상태에서는 무시한다.
   */
  J.toggleVoice = async function () {
    if (J.state.busy) return;
    if (J.state.isRecording) stopRecording();
    else await startRecording();
  };

  /**
   * 음성 전송
   *
   * 녹음된 오디오를 /voice 엔드포인트로 전송하고 응답을 처리한다.
   * 응답의 tools_used가 있으면 해당 도구 색상을 1.5초 표시 후 tts로 전환한다.
   *
   * @param {Blob} blob - 녹음된 오디오 Blob (webm/ogg)
   */
  J.sendVoice = async function (blob) {
    J.setBusy(true);
    try {
      const ext = blob.type.includes('webm') ? 'webm' : 'ogg';
      const form = new FormData();
      form.append('file', blob, `audio.${ext}`);
      if (J.state.currentSessionId) form.append('session_id', String(J.state.currentSessionId));

      const data = await apiFetch(API_ENDPOINTS.voice, { method: 'POST', body: form });
      if (data.session_id) J.state.currentSessionId = data.session_id;
      if (data.user_text) J.addMessage('user', data.user_text);
      if (data.answer) J.addMessage('assistant', data.answer);

      // 음성은 SSE가 없어 중간 도구 상태를 못 받음
      const playTts = () => {
        if (data.audio_b64) J.playAudio(data.audio_b64);
        else J.setSphereState('idle');
      };
      if (data.tools_used && data.tools_used.length) {
        J.setToolColor(data.tools_used[0]);
        J.setSphereState('tool', '');
        setTimeout(playTts, 1500);
      } else {
        playTts();
      }
    } catch (e) {
      J.addMessage('assistant', '음성 처리 오류가 발생했습니다.');
      J.setSphereState('idle');
      console.error('sendVoice 실패', e);
    } finally {
      J.setBusy(false);
    }
  };

  /**
   * 2. 오디오 재생 (구체 tts 연동)
   *
   * base64 mp3를 재생하고 구체를 tts 상태로 전환한다.
   * 재생 완료/오류 시 idle로 복귀한다.
   *
   * @param {string} b64 - base64 인코딩된 mp3 오디오
   */
  J.playAudio = function (b64) {
    if (J.state.currentAudio) { J.state.currentAudio.pause(); J.state.currentAudio = null; }
    const a = new Audio(`data:audio/mp3;base64,${b64}`);
    J.state.currentAudio = a;
    J.setSphereState('tts');
    a.onended = () => {
      if (J.state.currentAudio === a) { J.state.currentAudio = null; J.setSphereState('idle'); }
    };
    a.onerror = () => { J.setSphereState('idle'); };
    a.play().catch(() => J.setSphereState('idle'));
  };

})(window.JARVIS);