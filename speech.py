"""Opt-in ElevenLabs, persistent conservative budget and content-addressed WAV cache."""
import base64
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import sqlite3
import threading
import urllib.request
import uuid
from audio import RATE, wav_bytes, read_wav


class SpeechError(RuntimeError):
    pass


def fetch(url, key, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        'xi-api-key': key, 'Content-Type': 'application/json'}, method='POST')
    # API redirects are rejected: credentials must never be sent to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=12) as response:
        data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise SpeechError('ResponseTooLarge')
        return json.loads(data)


class SpeechClient:
    def __init__(self, settings, directory, transport=fetch):
        self.settings, self.transport = settings, transport
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ledger = self.directory / 'budget.sqlite3'
        with sqlite3.connect(self.ledger) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, chars INTEGER, estimate REAL)')

    def reserve(self, count):
        s = self.settings
        estimate = count * s.eleven_usd_per_1000 / 1000
        if count < 1 or not math.isfinite(estimate) or estimate <= 0:
            raise SpeechError('BudgetNotConfigured')
        with sqlite3.connect(self.ledger, timeout=2) as db:
            db.execute('BEGIN IMMEDIATE')
            chars, spent = db.execute('SELECT COALESCE(SUM(chars),0), COALESCE(SUM(estimate),0) FROM requests').fetchone()
            if chars + count > s.eleven_max_chars or spent + estimate > s.eleven_max_usd + 1e-10:
                raise SpeechError('BudgetExceeded')
            db.execute('INSERT INTO requests VALUES (?,?,?)', (uuid.uuid4().hex, count, estimate))
        # Failures remain reserved: the provider may already have billed them.

    def generate(self, text, speaker):
        s = self.settings
        if not s.eleven_enabled:
            raise SpeechError('Disabled')
        if speaker not in (0, 1) or not isinstance(text, str) or not 1 <= len(text) <= 600:
            raise SpeechError('InvalidText')
        voice = s.eleven_voice_1 if speaker == 0 else s.eleven_voice_2
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', voice):
            raise SpeechError('InvalidVoiceID')
        config = {'text': text, 'voice': voice, 'model': s.eleven_model, 'format': 'pcm_24000', 'schema': 1}
        digest = hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        wav = self.directory / (digest + '.wav')
        meta = self.directory / (digest + '.json')
        if wav.exists() and meta.exists():
            try:
                info = json.loads(meta.read_text(encoding='utf-8'))
                samples = read_wav(wav)
                if info.get('config') == config and abs(info['duration'] - len(samples) / RATE) < .001:
                    return wav, info
            except (OSError, ValueError, KeyError):
                pass
        self.reserve(len(text))
        try:
            response = self.transport('https://api.elevenlabs.io/v1/text-to-speech/' + voice +
                                      '/with-timestamps?output_format=pcm_24000', s.eleven_key,
                                      {'text': text, 'model_id': s.eleven_model})
            raw = base64.b64decode(response['audio_base64'], validate=True)
            if not raw or len(raw) % 2 or len(raw) > RATE * 2 * 60:
                raise ValueError('Invalid PCM')
            duration = len(raw) / (2 * RATE)
            alignment = response.get('normalized_alignment') or response.get('alignment')
            if alignment is not None:
                starts, ends = alignment['character_start_times_seconds'], alignment['character_end_times_seconds']
                if not len(starts) == len(ends) == len(alignment['characters']):
                    raise ValueError('Invalid alignment')
                previous = 0
                for start, end in zip(starts, ends):
                    if isinstance(start, bool) or isinstance(end, bool) or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (start, end)):
                        raise ValueError('Invalid timing')
                    if not previous <= start <= end <= duration + .1:
                        raise ValueError('Invalid timing')
                    previous = start
            info = {'config': config, 'duration': duration, 'alignment': alignment}
            # Unique temporary files; only complete files become visible cache entries.
            token = uuid.uuid4().hex
            temporary = wav.with_suffix('.' + token + '.tmp')
            temporary.write_bytes(wav_bytes(raw))
            temporary.replace(wav)
            temporary = meta.with_suffix('.' + token + '.tmp')
            temporary.write_text(json.dumps(info, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            temporary.replace(meta)
            return wav, info
        except Exception as exc:
            # Never expose HTTP headers, response bodies or exception messages.
            raise SpeechError(type(exc).__name__) from None


class SpeechWorker:
    def __init__(self, client):
        self.client = client
        self.jobs, self.results = queue.Queue(maxsize=3), queue.Queue()
        self.lock = threading.Lock()
        self.closed = False
        self.thread = threading.Thread(target=self.run, daemon=True, name='carrom-voice')
        self.thread.start()

    def submit(self, cue):
        with self.lock:
            if self.closed:
                return False
            try:
                self.jobs.put_nowait(cue)
                return True
            except queue.Full:
                return False

    def run(self):
        while True:
            cue = self.jobs.get()
            if cue is None:
                return
            with self.lock:
                if self.closed:
                    return
            try:
                result = self.client.generate(cue['text'], cue['speaker'])
                self.results.put((cue, result, None))
            except Exception as exc:
                self.results.put((cue, None, str(exc) if isinstance(exc, SpeechError) else type(exc).__name__))

    def close(self):
        with self.lock:
            self.closed = True
            while not self.jobs.empty():
                try:
                    self.jobs.get_nowait()
                except queue.Empty:
                    break
            self.jobs.put_nowait(None)
        # In-flight request may finish caching, but cannot mutate the game/session.
