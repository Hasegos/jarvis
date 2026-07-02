'use strict';

/**
 * @file 감정 추론 모듈 — 텍스트(키워드·이모지·문장부호)에서 감정 키를 추론한다.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.emotion = (() => {
  const DEFAULT = 'neutral';

  // 우선순위 순서 (강한 신호 먼저). 첫 매칭 감정을 반환.
  const RULES = [
    { key: 'sad',       re: /ㅠㅠ|ㅜㅜ|슬프|아쉽|미안|죄송|안타|눈물|😢|😭/ },
    { key: 'angry',     re: /화나|화가|짜증|열받|싫어|😠|😡|😤/ },
    { key: 'surprised', re: /헐|대박|깜짝|세상에|놀라|맙소사|[!?]{2,}|😲|😳|😱/ },
    { key: 'happy',     re: /ㅎㅎ|ㅋㅋ|하하|히히|헤헤|기뻐|기쁘|좋아|축하|신나|최고|행복|😊|😄|😁|🥰/ },
    { key: 'curious',   re: /궁금|어떻게|무엇|왜(?![가-힣])|뭐|\?\s*$/ },
  ];

  /**
   * 텍스트에서 감정 키를 추론한다.
   * 
   * @param {string} text - 분석할 텍스트
   * @returns {string} 'happy'|'sad'|'angry'|'surprised'|'curious'|'neutral'
   */
  function detect(text) {
    if (!text) return DEFAULT;
    const t = String(text);
    for (const rule of RULES) {
      if (rule.re.test(t)) return rule.key;
    }
    return DEFAULT;
  }

  return { detect };
})();