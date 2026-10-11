"""Original procedural audio; mixer access belongs exclusively to the UI thread."""
from array import array
import io
import math
import random
import sys
import wave
from pathlib import Path

RATE = 24000
SOUNDS = ('shot', 'impact', 'wall', 'pocket', 'foul', 'queen', 'end')


def pcm(name):
    if name not in (*SOUNDS, 'music'):
        raise ValueError('Unknown sound')
    rng = random.Random(name)
    duration = {'shot': .11, 'impact': .065, 'wall': .09, 'pocket': .38,
                'foul': .45, 'queen': .7, 'end': .9, 'music': 8}[name]
    values = array('h')
    for i in range(round(duration * RATE)):
        t = i / RATE
        if name == 'music':
            # Original quiet eight-beat arpeggio; no recordings or borrowed melody.
            note = (130.81, 164.81, 196, 261.63, 196, 164.81, 146.83, 196)[int(t) % 8]
            value = .12 * math.sin(2 * math.pi * note * t) * math.sin(math.pi * (t % 1)) ** 2
        elif name in ('shot', 'impact', 'wall'):
            freq = {'shot': 260, 'impact': 1250, 'wall': 410}[name]
            value = (.5 * rng.uniform(-1, 1) + .45 * math.sin(2 * math.pi * freq * t)) * math.exp(-65 * t)
        elif name == 'pocket':
            value = .65 * math.sin(2 * math.pi * (160 * t - 120 * t * t)) * math.exp(-12 * t)
        else:
            notes = {'foul': (330, 247), 'queen': (523, 659, 784), 'end': (392, 523, 659, 784)}[name]
            phase = t * len(notes) / duration
            value = .32 * math.sin(2 * math.pi * notes[min(int(phase), len(notes) - 1)] * t) * math.sin(math.pi * (phase % 1))
        values.append(round(max(-1, min(1, value)) * 32767))
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


def wav_bytes(raw):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(raw)
    return stream.getvalue()


def read_wav(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
            raise ValueError('Expected mono 24 kHz PCM16 WAV')
        if source.getnframes() > RATE * 60:
            raise ValueError('Voice clip too long')
        data = array('h', source.readframes(source.getnframes()))
        if sys.byteorder != 'little':
            data.byteswap()
        return data


class AudioPlayer:
    def __init__(self, pg, settings):
        self.pg, self.settings = pg, settings
        self.enabled, self.muted = settings.audio_enabled, False
        self.master = settings.audio_master
        self.warning = ''
        self.voice = None
        self.music = None
        self.sounds = {}
        if not self.enabled:
            return
        try:
            if pg.mixer.get_init() != (RATE, -16, 1):
                pg.mixer.quit()
                pg.mixer.init(RATE, -16, 1, 512)
            pg.mixer.set_num_channels(24)
            pg.mixer.set_reserved(2)
            self.voice, self.music = pg.mixer.Channel(0), pg.mixer.Channel(1)
            self.sounds = {name: pg.mixer.Sound(file=io.BytesIO(wav_bytes(pcm(name)))) for name in SOUNDS}
            if settings.audio_music > 0:
                self.music.play(pg.mixer.Sound(file=io.BytesIO(wav_bytes(pcm('music')))), loops=-1)
            self.volume()
        except pg.error:
            self.enabled = False
            self.warning = 'Аудиоустройство недоступно; текст и экспорт работают'

    def volume(self):
        if self.enabled:
            gain = 0 if self.muted else self.master
            self.music.set_volume(gain * self.settings.audio_music)
            self.voice.set_volume(gain * self.settings.audio_voice)

    def control(self, key):
        if key == self.pg.K_m:
            self.muted = not self.muted
        elif key in (self.pg.K_MINUS, self.pg.K_KP_MINUS):
            self.master = max(0, self.master - .1)
        elif key in (self.pg.K_EQUALS, self.pg.K_PLUS, self.pg.K_KP_PLUS):
            self.master = min(1, self.master + .1)
        self.volume()

    def sound(self, name, strength=1):
        gain = self.master * self.settings.audio_sfx * strength if self.enabled and not self.muted else 0
        if gain:
            channel = self.pg.mixer.find_channel()
            if channel:
                channel.set_volume(gain)
                channel.play(self.sounds[name])
            else:
                gain = 0
        return gain

    def speech(self, path):
        gain = self.master * self.settings.audio_voice if self.enabled and not self.muted else 0
        if not gain or self.voice.get_busy():
            return 0
        try:
            self.voice.play(self.pg.mixer.Sound(str(path)))
            self.voice.set_volume(gain)
            return gain
        except self.pg.error:
            return 0

    def stop_speech(self):
        if self.enabled:
            self.voice.stop()

    def close(self):
        if self.enabled:
            self.pg.mixer.stop()


def mix_stem(path, clips, duration):
    """Sparse streaming mix, bounded memory even for long API waits."""
    if not math.isfinite(duration) or not 0 <= duration <= 6 * 3600:
        raise ValueError('Audio export exceeds six-hour limit')
    sources = sorted(((max(0, round(start * RATE)), data, gain) for start, data, gain in clips), key=lambda item: item[0])
    total = round(duration * RATE)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        active, cursor = [], 0
        for base in range(0, total, 8192):
            count = min(8192, total - base)
            while cursor < len(sources) and sources[cursor][0] < base + count:
                active.append(sources[cursor])
                cursor += 1
            active = [item for item in active if item[0] + len(item[1]) > base]
            sums = [0.] * count
            for start, data, gain in active:
                low, high = max(base, start), min(base + count, start + len(data))
                for i in range(low, high):
                    sums[i - base] += data[i - start] * gain
            block = array('h', (round(max(-32768, min(32767, value))) for value in sums))
            if sys.byteorder != 'little':
                block.byteswap()
            output.writeframes(block.tobytes())
