from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # ───────────────────────────
    # 1.데이터 베이스(Postgresql)
    # ───────────────────────────
    POSTGRESQL_USERNAME: str
    POSTGRESQL_PASSWORD: str
    POSTGRESQL_SERVER: str
    POSTGRESQL_PORT: str
    POSTGRESQL_DATABASE: str
    PROJECT_NAME: str = "Jarvis"

    # DB 커넥션 풀
    POOL_SIZE: int
    MAX_OVERFLOW: int
    POOL_RECYCLE: int
    POOL_TIMEOUT: int
    POOL_PRE_PING: bool

    # DB 생성여부 (update)
    AUTO_CREATE_TABLES: bool

    # ───────────────────────────
    # 2. STT (faster-whisper)
    # ───────────────────────────
    STT_SERVER_URL: str
    STT_MODEL_DIR: str            # 모델 저장 경로
    STT_MODEL_SIZE: str           # 데스크탑 GPU 고정
    STT_DEVICE: str
    STT_COMPUTE_TYPE: str
    STT_LANGUAGE: str
    STT_SAMPLE_RATE: int          # Whisper 기대 입력 (Hz)
    STT_MIN_SPEECH_SECONDS: float # 이 미만이면 STT 스킵
    STT_TIMEOUT: float            # STT 서버 호출 타임아웃

    # ───────────────────────────
    # 3. TTS (Edge TTS)
    # ───────────────────────────
    TTS_VOICE: str
    TTS_RATE: str
    TTS_TIMEOUT: int

    # ───────────────────────────
    # 4. LM Studio 모델
    # ───────────────────────────
    LM_STUDIO_BASE_URL: str       # Docker 시 host.docker.internal
    LM_STUDIO_MODEL: str          
    LM_STUDIO_API_KEY: str
    LM_STUDIO_TIMEOUT: int        # seconds
    LM_STUDIO_EMBEDDING_MODEL: str

    # LLM 생성 파라미터
    LLM_TEMPERATURE: float
    LLM_TOP_P: float
    LLM_TOP_K: int
    LLM_REPEAT_PENALTY: float
    LLM_MAX_TOKENS: int
    LLM_STREAMING: bool
    HISTORY_LIMIT: int
    LLM_THINKING_MODE: str

    # Obsidian wiki
    WIKI_VAULT_PATH: str
    VAULT_WRITE_PATH: str

    # 웹 검색 (Tavily)
    TAVILY_API_KEY: str 

    # 네이버 지도
    NAVER_MAP_CLIENT_ID: str
    NAVER_MAP_CLIENT_SECRET: str

    # ──────────────────────────
    # 5. 계산된 프로퍼티 (DB URL)
    # ──────────────────────────
    @property
    def SQLALCHEMY_DATABASE_URL(self) -> str:
        """
        입력된 정보를 바탕으로 SQLAlchemy 접속 URL을 생성한다.
        """
        return (
            f"postgresql://{self.POSTGRESQL_USERNAME}:{self.POSTGRESQL_PASSWORD}"
            f"@{self.POSTGRESQL_SERVER}:{self.POSTGRESQL_PORT}/{self.POSTGRESQL_DATABASE}"
            f"?client_encoding=utf8"
        )

    # ──────────────────────────
    # 6. 환경 설정 로드 구성
    # ──────────────────────────
    model_config = SettingsConfigDict(
        env_file = ".env",
        env_file_encoding = "utf-8",
        extra = "ignore",
    )


# ──────────────────────
# 7. 설정 객체 인스턴스화
# ──────────────────────
settings = Settings()