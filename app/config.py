from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    bootstrap_token: str | None = None
    recommender: str | None = None
    static_dir: Path | None = None
    ai_timeout: float = 9.0
    testing: bool = False
    seed_data_dir: Path | None = None

    @classmethod
    def from_env(cls):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        default = base / "CareerQuest" / "instances" / "hack-9be09345-jassai"
        static = os.environ.get("CAREERQUEST_STATIC_DIR")
        seed = os.environ.get("CAREERQUEST_SEED_DATA_DIR")
        return cls(
            data_dir=Path(os.environ.get("CAREERQUEST_DATA_DIR", default)).resolve(),
            bootstrap_token=os.environ.get("CAREERQUEST_BOOTSTRAP_TOKEN"),
            recommender=os.environ.get("CAREERQUEST_RECOMMENDER"),
            static_dir=Path(static).resolve() if static else None,
            ai_timeout=min(9.0, max(0.1, float(os.environ.get("CAREERQUEST_AI_TIMEOUT", "9")))),
            seed_data_dir=(
                None if seed is not None and seed.strip().lower() == "off"
                else Path(seed).expanduser().resolve() if seed
                else Path(__file__).resolve().parents[1] / "starter-data"
            ),
        )
