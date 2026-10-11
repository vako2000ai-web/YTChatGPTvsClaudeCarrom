"""Local event commentary, independent live/replay clocks, SRT and separate WAV stems."""
from array import array
import bisect
import json
import math
from pathlib import Path
import queue
import time
import threading
from audio import RATE, SOUNDS, pcm, read_wav, mix_stem
from board import PLAYERS
from speech import SpeechClient, SpeechWorker


def commentary(player, pocketed, resolution, rules):
    name = PLAYERS[player]
    events = resolution.events
    if any('timeout_aborted' in event for event in events):
        return 'Физика превысила технический лимит. Победитель не назначается.', 'foul'
    if rules.finished:
        if rules.winner is not None:
            return 'Борд выиграл ' + PLAYERS[rules.winner] + '.', 'end'
        return 'Борд завершён без победителя: ' + str(rules.finish_reason) + '.', 'foul'
    if resolution.foul:
        return name + ': фол. Судья применил штраф и возвраты фишек.', 'foul'
    if any('queen_covered' in event for event in events):
        return name + ' покрыл королеву.', 'queen'
    if any('cover_required' in event or 'queen_needs_cover' in event for event in events):
        return name + ' забил королеву. Теперь требуется покрытие.', 'queen'
    if 'queen_returned' in events:
        return 'Королева возвращена на доску.', 'foul'
    count = sum(kind != 'striker' for _, kind in pocketed)
    if count:
        # A pocket is not automatically a kept/scored coin; referee may return it.
        return f'{name}: в лузы попало фишек — {count}. На доску возвращено — {len(resolution.returned)}.', None
    return name + ': без попаданий. Геометрия взяла тайм-аут! (Авторская шутка)', None


def stamp(seconds):
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid subtitle time')
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{sec:02},{ms:03}'


def subtitles(cues, duration):
    lines = []
    cues = sorted(cues, key=lambda cue: cue['start'])
    for index, cue in enumerate(cues):
        start = cue['start']
        end = min(cue['end'], duration, cues[index + 1]['start'] if index + 1 < len(cues) else duration)
        if end - start < .001:
            continue
        text = ' '.join(str(cue['text']).split()).replace('-->', '→')
        lines.append(f'{len(lines) + 1}\n{stamp(start)} --> {stamp(end)}\n{text}\n')
    return '\n'.join(lines)


class MediaSession:
    def __init__(self, log_path, settings, live=False, clock=time.monotonic, speech_client=None):
        self.directory = Path(log_path).with_suffix('.media')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings, self.live, self.clock = settings, live, clock
        self.origin = clock()
        self.events, self.pending, self.voices = [], [], []
        self.replay_time = 0
        self.closed = False
        self.export_thread = None
        self.export_error = None
        self.latest = ''
        self.latest_until = 0
        self.status = ''
        self.obs_start = None
        self.video_file = None
        self.worker = None
        if live and settings.audio_enabled and settings.eleven_enabled:
            cache = self.directory.parent / '.voice-cache'
            self.worker = SpeechWorker(speech_client or SpeechClient(settings, cache))
        self.file = (self.directory / 'events.jsonl').open('x', encoding='utf-8')

    def now(self):
        return max(0, self.clock() - self.origin) if self.live else self.replay_time

    def update(self, replay_time):
        self.replay_time = replay_time

    def write(self, event, **data):
        if self.closed:
            return None
        item = {'event': event, 'time': self.now(), 'replay_time': self.replay_time, **data}
        self.events.append(item)
        self.file.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + '\n')
        self.file.flush()
        return item

    def sound(self, name, strength=1):
        if name not in SOUNDS:
            raise ValueError('Invalid SFX')
        self.pending.append((name, max(0, min(1, strength))))
        if not self.live:
            name, strength = self.pending.pop()
            self.write('sound', name=name, gain=self.settings.audio_master * self.settings.audio_sfx * strength)

    def player_comment(self, player, text):
        if text.strip():
            self.write('player', text=PLAYERS[player] + ': ' + text, source='public-player-comment', duration=4)

    def completed(self, player, pocketed, resolution, rules):
        text, sound = commentary(player, pocketed, resolution, rules)
        cue = self.write('commentator', text=text, speaker=rules.turn % 2,
                         source='authored-commentary', duration=5)
        self.latest, self.latest_until = text, self.now() + 5
        if sound:
            self.sound(sound)
        if self.worker and cue and not self.worker.submit(cue):
            self.status = 'Очередь озвучки заполнена; текст сохранён'

    def interruption(self, player, reason):
        text = PLAYERS[player] + ': ход пропущен из-за ' + reason + '. Это техническое событие.'
        self.write('commentator', text=text, speaker=player, source='authored-commentary', duration=5)
        self.latest, self.latest_until = text, self.now() + 5
        self.sound('foul')

    def tick(self, player):
        if self.closed:
            return
        while self.pending:
            name, strength = self.pending.pop(0)
            gain = player.sound(name, strength)
            self.write('sound', name=name, gain=gain)
        if self.worker:
            while True:
                try:
                    cue, result, error = self.worker.results.get_nowait()
                except queue.Empty:
                    break
                if error:
                    self.status = 'Озвучка: ' + error + '; текст сохранён'
                    self.write('voice_failed', error_type=error)
                else:
                    self.voices.append((cue, result))
        if self.voices and (not player.enabled or not player.voice.get_busy()):
            cue, (path, info) = self.voices.pop(0)
            if self.now() - cue['time'] > 15:
                self.write('voice_skipped', reason='stale')
                return
            gain = player.speech(path)
            if gain:
                # Subtitle start is playback start, never the TTS request time.
                target = self.directory / (path.stem + '.wav')
                if not target.exists():
                    target.write_bytes(path.read_bytes())
                self.write('voice', text=cue['text'], source='authored-commentary',
                                  clip=target.name, duration=info['duration'], gain=gain, speaker=cue['speaker'],
                                  alignment=info['alignment'])
                self.latest, self.latest_until = cue['text'], self.now() + info['duration']

    def close(self, background=False):
        if self.closed:
            return
        duration = self.now()
        if self.worker:
            self.worker.close()
        self.write('session_end')
        self.closed = True
        self.file.close()
        if background:
            self.export_thread = threading.Thread(target=self._safe_export, args=(duration,), name='carrom-media-export')
            self.export_thread.start()
        else:
            self._export(duration)

    def _safe_export(self, duration):
        try:
            self._export(duration)
        except Exception as exc:
            self.export_error = type(exc).__name__
            (self.directory / 'export-error.txt').write_text(self.export_error, encoding='utf-8')

    def wait_export(self):
        if self.export_thread:
            self.export_thread.join()
        if self.export_error:
            raise RuntimeError('Media export failed: ' + self.export_error)
        # OBS may finish after a preceding board's background export.
        path = self.directory / 'manifest.json'
        if path.exists() and self.video_file:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            manifest['video_file'] = self.video_file
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    def _export(self, duration):
        # Clip text and audio to actual session length, including early user exit.
        for kind in ('player', 'commentator', 'voice'):
            cues = [{'start': item['time'], 'end': item['time'] + item['duration'],
                     'text': ('[Авторский комментарий] ' if kind != 'player' else '') + item['text']}
                    for item in self.events if item['event'] == kind]
            (self.directory / (kind + '.srt')).write_text(subtitles(cues, duration), encoding='utf-8-sig')
        sounds = {name: array('h', pcm(name)) for name in SOUNDS}
        clips = [(item['time'], sounds[item['name']], item['gain']) for item in self.events if item['event'] == 'sound']
        mix_stem(self.directory / 'sfx.wav', clips, duration)
        voices = [(item['time'], read_wav(self.directory / item['clip']), item['gain'])
                  for item in self.events if item['event'] == 'voice']
        mix_stem(self.directory / 'voice-1.wav', [clip for clip, item in zip(voices, [e for e in self.events if e['event'] == 'voice']) if item['speaker'] == 0], duration)
        mix_stem(self.directory / 'voice-2.wav', [clip for clip, item in zip(voices, [e for e in self.events if e['event'] == 'voice']) if item['speaker'] == 1], duration)
        manifest = {'format': 'carrom-media-v1', 'timebase': 'live-monotonic' if self.live else 'replay-presentation',
                    'duration': duration, 'replay_duration': self.replay_time, 'sample_rate': RATE,
                    'video_file': self.video_file, 'video_offset': self.origin - self.obs_start if self.obs_start else None,
                    'obs_alignment': 'StartRecord acknowledgement; verify offset visually before editing',
                    'commentary_source': 'authored; not model responses', 'events': len(self.events)}
        (self.directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        (self.directory / 'CAPCUT.txt').write_text('Импортируйте исходник OBS и WAV/SRT. WAV/SRT начинаются с начала этого борда.\n'
            'video_offset в manifest задаёт сдвиг борда относительно OBS; проверьте по первому удару.\n'
            'Отключите звук видео при добавлении отдельных WAV, чтобы избежать удвоения.\n'
            'player.srt — публичные реплики игроков; commentator.srt — авторский текст; voice.srt — фактическое воспроизведение озвучки.\n'
            'После нарезки пересчитайте таймкоды. Replay не содержит ожиданий API.\n'
            'SFX созданы кодом проекта; музыкальный цикл выключен по умолчанию и в эти WAV не входит.\n', encoding='utf-8')


class ReplayMedia:
    """Only recorded events. Never creates a speech client or requests a model."""
    def __init__(self, path):
        self.events = []
        self.latest = ''
        self.cursor = 0
        directory = Path(str(path).removesuffix('.replay.jsonl.gz') + '.media')
        source = directory / 'events.jsonl'
        if not source.exists():
            return
        if source.stat().st_size > 16_000_000:
            raise ValueError('Media events exceed loading limit')
        with source.open(encoding='utf-8') as file:
            for line in file:
                item = json.loads(line)
                timestamp = item.get('replay_time')
                if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
                    raise ValueError('Invalid media time')
                if item.get('event') == 'sound' and item.get('name') in SOUNDS:
                    self.events.append(item)
                elif item.get('event') == 'commentator' and isinstance(item.get('text'), str):
                    self.events.append(item)
        self.events.sort(key=lambda item: item['replay_time'])
        self.times = [item['replay_time'] for item in self.events]

    def seek(self, timestamp, player):
        self.cursor = bisect.bisect_right(getattr(self, 'times', []), timestamp)
        self.latest = ''
        player.stop_speech()

    def advance(self, timestamp, player):
        while self.cursor < len(self.events) and self.events[self.cursor]['replay_time'] <= timestamp:
            event = self.events[self.cursor]
            self.cursor += 1
            if event['event'] == 'sound':
                # User's replay volume, not a new TTS request or physical simulation.
                player.sound(event['name'])
            else:
                self.latest = event['text']
