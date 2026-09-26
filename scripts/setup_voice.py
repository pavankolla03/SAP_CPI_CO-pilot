"""Explicit one-time model download. Inference is subsequently local-only."""
from pathlib import Path
from faster_whisper.utils import download_model

if __name__ == '__main__':
    target = Path('data/voice-model')
    download_model('base', output_dir=str(target))
    print('Local multilingual base model ready. Set VOICE_ENABLED=true and restart Relay.')
