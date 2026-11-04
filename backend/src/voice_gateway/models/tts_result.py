from pathlib import Path

from pydantic import BaseModel, Field, AliasChoices


class TTSResult(BaseModel):
    """Verified audio result; format is explicit, independent of the filename.

    wav_path remains accepted during the legacy firmware transition.
    """
    audio_path: Path = Field(validation_alias=AliasChoices("audio_path", "wav_path"))
    sample_rate: int
    codec: str = "wav"
    media_type: str = "audio/wav"
    channels: int = 1

    @property
    def wav_path(self) -> Path:
        return self.audio_path
