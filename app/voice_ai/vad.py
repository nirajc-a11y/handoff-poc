"""Silero VAD wrapper for real-time voice activity detection.

Replaces energy-based (audioop.rms) detection with a neural model that
handles background noise, echo, and varying phone conditions without
per-deployment threshold tuning.

Uses ONNX backend (~2MB model, <1ms inference) for lightweight deployment.
Each VADProcessor instance has independent LSTM state, safe for concurrent sessions.

Usage:
    vad = VADProcessor(profile="ai_conversation")
    for mulaw_chunk in audio_stream:
        result = vad.process_chunk(mulaw_chunk)
        if result.is_speech:
            ...  # buffer audio
"""

import logging
from dataclasses import dataclass, replace

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop  # type: ignore[no-redef]

import numpy as np
import torch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resolve the ONNX model file path once at module level.
# Each VADProcessor creates its own OnnxWrapper instance from this path
# so that LSTM state is fully isolated per session.
# ---------------------------------------------------------------------------

_model_path: str | None = None


def _get_model_path() -> str:
    global _model_path
    if _model_path is None:
        package_path = "silero_vad.data"
        model_name = "silero_vad.onnx"
        try:
            import importlib_resources as impresources
            _model_path = str(impresources.files(package_path).joinpath(model_name))
        except Exception:
            from importlib import resources as impresources
            _model_path = str(impresources.files(package_path).joinpath(model_name))
        logger.info("Silero VAD ONNX model path resolved: %s", _model_path)
    return _model_path


def _create_model():
    """Create a new ONNX VAD model instance with independent state."""
    from silero_vad.utils_vad import OnnxWrapper
    return OnnxWrapper(_get_model_path())


# ---------------------------------------------------------------------------
# Endpointing profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VADConfig:
    threshold: float        # Speech confidence threshold (0-1)
    min_speech_ms: int      # Minimum speech duration to accept as real speech
    min_silence_ms: int     # Silence duration to trigger endpointing
    speech_pad_ms: int      # Padding to avoid cutting first phoneme

    @property
    def min_speech_chunks(self) -> int:
        """Number of 32ms VAD chunks for min_speech_ms."""
        return max(1, self.min_speech_ms // 32)

    @property
    def min_silence_chunks(self) -> int:
        """Number of 32ms VAD chunks for min_silence_ms."""
        return max(1, self.min_silence_ms // 32)


ENDPOINTING_PROFILES: dict[str, VADConfig] = {
    "ivr": VADConfig(
        threshold=0.5, min_speech_ms=200,
        min_silence_ms=300, speech_pad_ms=30,
    ),
    "ai_conversation": VADConfig(
        threshold=0.5, min_speech_ms=250,
        min_silence_ms=500, speech_pad_ms=30,
    ),
    "complaint": VADConfig(
        threshold=0.5, min_speech_ms=250,
        min_silence_ms=800, speech_pad_ms=30,
    ),
}


# ---------------------------------------------------------------------------
# VAD result
# ---------------------------------------------------------------------------

@dataclass
class VADResult:
    is_speech: bool
    probability: float


# ---------------------------------------------------------------------------
# Per-session VAD processor
# ---------------------------------------------------------------------------

class VADProcessor:
    """Per-session Silero VAD state machine.

    Each instance creates its own ONNX model with independent LSTM state,
    safe for concurrent sessions. Accepts mulaw 8kHz audio chunks of any
    size, accumulates to the required 256-sample (32ms) boundary, and runs
    Silero inference.
    """

    # Silero requires exactly 256 samples at 8kHz (32ms)
    CHUNK_SAMPLES = 256
    SAMPLE_RATE = 8000

    def __init__(self, profile: str = "ai_conversation", threshold: float | None = None):
        self.config = ENDPOINTING_PROFILES.get(profile, ENDPOINTING_PROFILES["ai_conversation"])
        if threshold is not None:
            self.config = replace(self.config, threshold=threshold)

        # Per-instance model: independent LSTM state, safe for concurrency
        self._model = _create_model()
        # Internal PCM sample buffer to accumulate to 256-sample boundary
        self._pcm_buffer = np.empty(0, dtype=np.int16)
        # Last result (returned when buffer hasn't hit 256 yet)
        self._last_result = VADResult(is_speech=False, probability=0.0)

    def process_chunk(self, mulaw_chunk: bytes) -> VADResult:
        """Process a mulaw 8kHz audio chunk through Silero VAD.

        Accumulates samples internally. Returns the latest VAD result.
        If not enough samples have accumulated for a new inference,
        returns the result from the previous inference call.
        """
        # mulaw -> 16-bit PCM at 8kHz
        pcm_bytes = audioop.ulaw2lin(mulaw_chunk, 2)
        pcm_samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        self._pcm_buffer = np.concatenate([self._pcm_buffer, pcm_samples])

        # Process all complete 256-sample windows
        while len(self._pcm_buffer) >= self.CHUNK_SAMPLES:
            window = self._pcm_buffer[:self.CHUNK_SAMPLES]
            self._pcm_buffer = self._pcm_buffer[self.CHUNK_SAMPLES:]

            # int16 -> float32 normalized [-1, 1]
            audio_float = window.astype(np.float32) / 32768.0
            tensor = torch.from_numpy(audio_float)

            prob = self._model(tensor, self.SAMPLE_RATE).item()
            self._last_result = VADResult(
                is_speech=prob >= self.config.threshold,
                probability=prob,
            )

        return self._last_result

    def reset(self):
        """Reset VAD state (call between turns to clear LSTM memory)."""
        self._model.reset_states()
        self._pcm_buffer = np.empty(0, dtype=np.int16)
        self._last_result = VADResult(is_speech=False, probability=0.0)
