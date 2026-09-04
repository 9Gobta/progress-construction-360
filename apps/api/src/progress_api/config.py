from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Progress Construction AI"
    api_v1_prefix: str = "/api/v1"
    web_origin: str = "http://localhost:3000"

    database_url: str = "sqlite:///./progress-dev.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    jwt_secret_key: str = Field(
        default="development-only-secret-change-before-deployment",
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "progress"
    s3_secret_key: str = "change-this-minio-password"
    s3_bucket: str = "progress-construction"
    s3_region: str = "us-east-1"
    s3_secure: bool = False

    # Local development storage safety. When MinIO and the worker run on the
    # same Windows machine, uploads must stop before Docker/temporary files
    # consume the system drive. Set both paths to an external SSD after moving
    # storage. Remote S3 providers can leave storage_guard_path unset.
    storage_guard_path: str | None = None
    storage_min_free_gb: float = Field(default=50.0, ge=1.0, le=10_000.0)
    processing_temp_dir: str | None = None
    processing_workspace_factor: float = Field(default=2.0, ge=0.5, le=10.0)
    # Optional read-only archive for locally linked source videos. Derived
    # assets remain in S3/MinIO; only the original large video stays here.
    external_media_root: str | None = None
    # Additional read-only archives separated by semicolons. This lets one
    # project reference source videos spread across multiple external drives.
    external_media_roots: str | None = None

    # Optional executable built around the licensed Insta360 Desktop MediaSDK.
    # When configured, raw X5 .insv uploads are stitched before the normal
    # equirectangular video pipeline runs.
    insta360_stitcher_path: str | None = None
    insta360_stitch_timeout_seconds: int = Field(default=7200, ge=60, le=86400)

    # Visual localization. Stella runs in a Linux container on the Windows
    # development machine and writes a TUM trajectory for the Python worker.
    localization_engine: str = "stella_vslam"
    stella_vslam_image: str = "progress-stella-vslam:0.7.0"
    stella_vslam_docker_path: str | None = None
    stella_vslam_vocab_path: str = ".runtime/stella/orb_vocab.fbow"
    stella_vslam_config_path: str = "infra/stella/x5-equirectangular.yaml"
    stella_vslam_timeout_seconds: int = Field(default=7200, ge=60, le=86400)
    stella_vslam_tracking_fps: int = Field(default=15, ge=2, le=30)
    stella_vslam_frame_skip: int = Field(default=1, ge=1, le=30)

    # Learned cross-capture relocalization. HLoc retrieves visually similar
    # perspective views and DISK + LightGlue verifies them before a historical
    # human-confirmed plan position is allowed to constrain a new Stella path.
    # Keep the large models/cache on the external processing SSD.
    hloc_source_path: str | None = None
    hloc_python_path: str | None = None
    hloc_torch_home: str | None = None
    hloc_reference_cache_path: str | None = None
    hloc_retrieval_candidates: int = Field(default=5, ge=1, le=20)
    hloc_min_geometric_inliers: int = Field(default=24, ge=8, le=500)
    hloc_max_reference_images: int = Field(default=96, ge=8, le=500)

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API_V1_PREFIX must start with '/'")
        return value.rstrip("/")

    @field_validator("localization_engine")
    @classmethod
    def validate_localization_engine(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"stella_vslam", "pycolmap"}:
            raise ValueError("LOCALIZATION_ENGINE must be stella_vslam or pycolmap")
        return normalized

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origin.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
