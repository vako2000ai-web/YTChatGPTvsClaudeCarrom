"""Read secrets only from the project's .env, never from a match log."""
from dataclasses import dataclass, field
from pathlib import Path
import sys
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

    @classmethod
    def load(cls, path=None, mode=None):
        values = dotenv_values(path or project_root() / '.env')
        settings = cls(mode=(mode or values.get('MODE') or 'demo').lower(),
                       openai_key=values.get('OPENAI_API_KEY') or '',
                       anthropic_key=values.get('ANTHROPIC_API_KEY') or '',
                       openai_model=values.get('OPENAI_MODEL') or '',
                       anthropic_model=values.get('ANTHROPIC_MODEL') or '',
                       timeout=float(values.get('API_TIMEOUT') or 25),
                       max_output_tokens=int(values.get('API_MAX_OUTPUT_TOKENS') or 1024))
        settings.validate()
        return settings

    def validate(self):
        if self.mode not in ('demo', 'api'):
            raise ValueError('MODE must be demo or api')
        if not 1 <= self.timeout <= 120 or not 256 <= self.max_output_tokens <= 8192:
            raise ValueError('API timeout/token limits are out of range')
        if self.mode == 'api':
            missing = [name for name, value in (
                ('OPENAI_API_KEY', self.openai_key), ('ANTHROPIC_API_KEY', self.anthropic_key),
                ('OPENAI_MODEL', self.openai_model), ('ANTHROPIC_MODEL', self.anthropic_model)) if not value.strip()]
            if missing:
                raise ValueError('Set these fields in .env: ' + ', '.join(missing))
