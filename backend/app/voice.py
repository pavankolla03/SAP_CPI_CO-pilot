"""Local, bounded transcription. Audio is never sent to the planning provider."""

import io
import threading
from pathlib import Path


class Transcriber:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.lock = threading.Lock()

    def status(self):
        return {
            "enabled": self.settings.voice_enabled,
            "provider": "local-faster-whisper",
            "model_ready": Path(self.settings.voice_model_path, "model.bin").is_file(),
            "max_seconds": 60,
            "max_bytes": 5_000_000,
        }

    def transcribe(self, audio):
        if not self.settings.voice_enabled:
            raise ValueError("Local transcription is disabled; see the voice setup guide")
        if not audio or len(audio) > 5_000_000:
            raise ValueError("Audio must be between 1 byte and 5 MB")
        if not self.lock.acquire(blocking=False):
            raise ValueError("Transcriber is busy; retry later")
        try:
            if not self.status()["model_ready"]:
                raise ValueError("Download the local speech model using scripts/setup_voice.py first")
            from faster_whisper import WhisperModel
            import av
            import numpy as np

            # Decode incrementally so a compressed, very long recording cannot allocate unbounded PCM.
            chunks, count = [], 0
            with av.open(io.BytesIO(audio)) as container:
                resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
                for frame in container.decode(audio=0):
                    for converted in resampler.resample(frame):
                        count += converted.samples
                        if count > 60 * 16000:
                            raise ValueError("Recordings must be at most 60 seconds")
                        chunks.append(converted.to_ndarray().flatten())
                for converted in resampler.resample(None):
                    count += converted.samples
                    if count > 60 * 16000:
                        raise ValueError("Recordings must be at most 60 seconds")
                    chunks.append(converted.to_ndarray().flatten())
            if not chunks:
                raise ValueError("No audio was found")
            if self.model is None:
                self.model = WhisperModel(
                    self.settings.voice_model_path,
                    device="cpu",
                    compute_type="int8",
                    local_files_only=True,
                    cpu_threads=4,
                )
            pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
            segments, info = self.model.transcribe(
                pcm, beam_size=3, vad_filter=True, condition_on_previous_text=False
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text or len(text) > 2000:
                raise ValueError("No usable speech found; record a shorter, clearer instruction")
            return {
                "text": text,
                "language": info.language,
                "seconds": round(count / 16000, 2),
                "review_required": True,
                "provider": "local-faster-whisper",
            }
        except ImportError:
            raise ValueError("Install the voice extra: uv sync --extra voice") from None
        except ValueError:
            raise
        except Exception:
            raise ValueError(
                "Audio could not be transcribed; try a short WAV, OGG or WebM recording"
            ) from None
        finally:
            self.lock.release()
