"""Read secrets only from the project's .env, never from a match log."""
from dataclasses import dataclass, field
from pathlib import Path
import sys
import math
import re
from dotenv import dotenv_values


def project_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    mode: str = 'demo'
    openai_key: str = field(default='', repr=False)
    anthropic_key: str = field(default='', repr=False)
    openai_model: str = ''
    anthropic_model: str = ''
    timeout: float = 25
    max_output_tokens: int = 1024
    obs_url: str = 'ws://127.0.0.1:4455'
    obs_password: str = field(default='', repr=False)

    audio_enabled: bool = True
    audio_master: float = .75
    audio_sfx: float = .8
    audio_music: float = 0
    audio_voice: float = .85
    eleven_enabled: bool = False
    eleven_key: str = field(default='', repr=False)
    eleven_voice_1: str = ''
    eleven_voice_2: str = ''
    eleven_model: str = 'eleven_multilingual_v2'
    eleven_max_chars: int = 2000
    eleven_max_usd: float = 1
    eleven_usd_per_1000: float = 0

    @classmethod
    def load(cls, path=None, mode=None, disable_audio=False, disable_voice=False):
        values = dotenv_values(path or project_root() / '.env')
        def flag(name, default):
            value = str(values.get(name) or default).lower()
            if value not in ('true', 'false', '1', '0'):
                raise ValueError(name + ' must be true/false')
            return value in ('true', '1')
        settings = cls(mode=(mode or values.get('MODE') or 'demo').lower(),
                       openai_key=values.get('OPENAI_API_KEY') or '',
                       anthropic_key=values.get('ANTHROPIC_API_KEY') or '',
                       openai_model=values.get('OPENAI_MODEL') or '',
                       anthropic_model=values.get('ANTHROPIC_MODEL') or '',
                       timeout=float(values.get('API_TIMEOUT') or 25),
                       max_output_tokens=int(values.get('API_MAX_OUTPUT_TOKENS') or 1024),
                       obs_url=values.get('OBS_URL') or 'ws://127.0.0.1:4455',
                       obs_password=values.get('OBS_PASSWORD') or '',
                       audio_enabled=False if disable_audio else flag('AUDIO_ENABLED', 'true'),
                       audio_master=float(values.get('AUDIO_MASTER_VOLUME') or .75),
                       audio_sfx=float(values.get('AUDIO_SFX_VOLUME') or .8),
                       audio_music=float(values.get('AUDIO_MUSIC_VOLUME') or 0),
                       audio_voice=float(values.get('AUDIO_VOICE_VOLUME') or .85),
                       eleven_enabled=False if disable_audio or disable_voice else flag('ELEVENLABS_ENABLED', 'false'),
                       eleven_key=values.get('ELEVENLABS_API_KEY') or '',
                       eleven_voice_1=values.get('ELEVENLABS_VOICE_ID_1') or '',
                       eleven_voice_2=values.get('ELEVENLABS_VOICE_ID_2') or '',
                       eleven_model=values.get('ELEVENLABS_MODEL') or 'eleven_multilingual_v2',
                       eleven_max_chars=int(values.get('ELEVENLABS_MAX_CHARACTERS') or 2000),
                       eleven_max_usd=float(values.get('ELEVENLABS_MAX_ESTIMATED_USD') or 1),
                       eleven_usd_per_1000=float(values.get('ELEVENLABS_USD_PER_1000_CHARACTERS') or 0))
        settings.validate()
        return settings

    def validate(self):
        if self.mode not in ('demo', 'api'):
            raise ValueError('MODE must be demo or api')
        if not 1 <= self.timeout <= 120 or not 256 <= self.max_output_tokens <= 8192:
            raise ValueError('API timeout/token limits are out of range')
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in
                   (self.audio_master, self.audio_sfx, self.audio_music, self.audio_voice)):
            raise ValueError('Audio volumes must be finite values in 0..1')
        if (self.eleven_max_chars < 1 or not math.isfinite(self.eleven_max_usd) or self.eleven_max_usd <= 0
                or not math.isfinite(self.eleven_usd_per_1000) or self.eleven_usd_per_1000 < 0):
            raise ValueError('Invalid ElevenLabs budget')
        if self.eleven_enabled:
            if not self.eleven_key.strip() or not all(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', voice)
                                                    for voice in (self.eleven_voice_1, self.eleven_voice_2)):
                raise ValueError('Set ElevenLabs key and two voice IDs in .env')
            if self.eleven_voice_1 == self.eleven_voice_2 or self.eleven_usd_per_1000 <= 0:
                raise ValueError('Use two distinct voice IDs and a positive conservative character price')
        if self.mode == 'api':
            missing = [name for name, value in (
                ('OPENAI_API_KEY', self.openai_key), ('ANTHROPIC_API_KEY', self.anthropic_key),
                ('OPENAI_MODEL', self.openai_model), ('ANTHROPIC_MODEL', self.anthropic_model)) if not value.strip()]
            if missing:
                raise ValueError('Set these fields in .env: ' + ', '.join(missing))
