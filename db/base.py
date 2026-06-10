from db.base_class import Base
from models.fact_model import Fact
from models.session_model import Session
from models.message_model import Message
from models.memory_profile_model import MemoryProfile

# ─────────────────────────────────────
# 1. 모델 통합 관리 (Alembic/Base 전용)
# ─────────────────────────────────────
# 이 파일은 Alembic 마이그레이션 도구가 모든 모델을 한 번에 인식하게 하거나,
# 애플리케이션 초기화 시 모든 테이블 정의를 로드하기 위해 사용됩니다.

# 1-1. Base: 모든 모델의 부모 클래스
# 1-2. Session : 대화 세션 (sessions 테이블)
# 1-3. Message : 대화 메시지 + 임베딩 (messages 테이블)
# 1-4. Fact    : 추출된 사실 + 임베딩 (facts 테이블)
# 1-5. MemoryProfile : 사용자 기억 프로필 (memory_profiles 테이블)