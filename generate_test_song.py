"""
Generates a simple synthesized test song (steady beeping beat) and a matching
chart JSON, so you can test the game immediately without needing real music.

Run:  python generate_test_song.py
Then: python main.py charts/sample_chart.json
"""

import json
import math
import os
import struct
import wave
import random

SAMPLE_RATE = 44100
BPM = 120
BEAT_MS = 60000 / BPM  # ms per beat
DURATION_SECONDS = 45
BEEP_DURATION_MS = 80
BEEP_FREQ = 880.0

OUT_DIR = os.path.dirname(__file__)
SONG_PATH = os.path.join(OUT_DIR, "songs", "test_song.wav")
CHART_PATH = os.path.join(OUT_DIR, "charts", "sample_chart.json")


def make_beep_samples(freq, duration_ms, sample_rate, volume=0.4):
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        # simple decay envelope so it doesn't click
        envelope = max(0.0, 1.0 - (i / n_samples))
        val = volume * envelope * math.sin(2 * math.pi * freq * t)
        samples.append(val)
    return samples


def main():
    os.makedirs(os.path.dirname(SONG_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)

    total_samples = int(SAMPLE_RATE * DURATION_SECONDS)
    audio = [0.0] * total_samples

    beat_times_ms = []
    t = 1000.0  # start 1 second in
    while t < DURATION_SECONDS * 1000 - 500:
        beat_times_ms.append(t)
        t += BEAT_MS

    beep = make_beep_samples(BEEP_FREQ, BEEP_DURATION_MS, SAMPLE_RATE)
    for beat_ms in beat_times_ms:
        start_sample = int(SAMPLE_RATE * beat_ms / 1000)
        for i, s in enumerate(beep):
            idx = start_sample + i
            if idx < total_samples:
                audio[idx] += s

    # Write WAV (16-bit PCM, mono)
    with wave.open(SONG_PATH, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for s in audio:
            s = max(-1.0, min(1.0, s))
            frames += struct.pack("<h", int(s * 32767))
        wf.writeframes(bytes(frames))

    # Build a matching chart: one note per beat, random lane, occasional chords
    random.seed(42)
    notes = []
    for beat_ms in beat_times_ms:
        lane = random.randint(0, 3)
        notes.append({"time_ms": round(beat_ms), "lane": lane})
        if random.random() < 0.12:
            other_lane = random.choice([l for l in range(4) if l != lane])
            notes.append({"time_ms": round(beat_ms), "lane": other_lane})

    chart = {
        "title": "Test Beat (120 BPM)",
        "song": "songs/test_song.wav",
        "offset_ms": 0,
        "notes": notes,
    }
    with open(CHART_PATH, "w") as f:
        json.dump(chart, f, indent=2)

    print(f"Wrote {SONG_PATH} ({DURATION_SECONDS}s)")
    print(f"Wrote {CHART_PATH} ({len(notes)} notes)")


if __name__ == "__main__":
    main()
