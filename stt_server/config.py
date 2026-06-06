from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ─────────────────────────────────────
    # 1. STT (faster-whisper)
    # ─────────────────────────────────────
    STT_MODEL_DIR    : str   = r"D:\01_WORK\03_Project\01_AI model"
    STT_MODEL_SIZE   : str   = "medium"
    STT_DEVICE       : str   = "cuda"
    STT_COMPUTE_TYPE : str   = "float16"
    STT_LANGUAGE     : str   = "ko"
    STT_SERVER_PORT  : int   = 8001

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()