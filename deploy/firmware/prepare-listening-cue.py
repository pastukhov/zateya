#!/usr/bin/env python3
"""Validate an already generated listening cue and package public firmware assets."""
import argparse
import hashlib
import json
import wave
from pathlib import Path


def prepare(source: Path, output: Path, model: str, voice: str) -> dict:
    with wave.open(str(source), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 24000, 'NONE'):
            raise ValueError('cue must be PCM16 mono 24000 Hz')
        frames = wav.getnframes()
        if not 0 < frames <= 120000:
            raise ValueError('cue must be nonempty and at most 5 seconds')
        pcm = wav.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError('truncated cue')
    metadata = dict(text='Слушаю.', model=model, voice=voice, sample_rate=24000,
                    channels=1, bits_per_sample=16, frames=frames,
                    sha256=hashlib.sha256(pcm).hexdigest())
    output.mkdir(parents=True, exist_ok=True)
    (output / 'listening.pcm').write_bytes(pcm)
    (output / 'listening.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    return metadata

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--model',required=True)
    parser.add_argument('--voice',required=True)
    args=parser.parse_args()
    metadata=prepare(args.source,args.output,args.model,args.voice)
    print(f"Cue ready: {metadata['frames']/24000:.2f}s, SHA256 {metadata['sha256']}")
