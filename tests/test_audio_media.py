import base64
from dataclasses import replace
import json
import sqlite3
import time
from types import SimpleNamespace as NS
import wave
from array import array
import pytest
from audio import RATE, SOUNDS, pcm, wav_bytes, mix_stem
from engine import Board
from settings import Settings
from rules import Resolution
from media import MediaSession, ReplayMedia, commentary, subtitles, stamp
from speech import SpeechClient, SpeechError, SpeechWorker


def voice_settings(**kwargs):
    return replace(Settings(), eleven_enabled=True, eleven_key='DO-NOT-LEAK',
                   eleven_voice_1='voice-one', eleven_voice_2='voice-two',
                   eleven_usd_per_1000=1, **kwargs)


@pytest.mark.parametrize('name', (*SOUNDS, 'music'))
def test_original_sounds_are_non_silent_pcm_without_clipping(name):
    raw = pcm(name)
    samples = array('h', raw)
    assert min(samples) < -100 < 100 < max(samples) < 32767
    assert raw == pcm(name)
    with wave.open(__import__('io').BytesIO(wav_bytes(raw))) as file:
        assert (file.getframerate(), file.getnchannels(), file.getsampwidth()) == (RATE, 1, 2)


def test_sound_observation_does_not_change_collision_rules():
    board = Board(official=True)
    board.shoot({'x': 380, 'angle': 270, 'power': .8}, 0)
    assert board.drain_sounds()[0][0] == 'shot'
    emitted = []
    while board.active:
        board.step()
        emitted.extend(board.drain_sounds())
    assert board.touched and any(name == 'impact' for name, _ in emitted)
    assert all(0 < gain <= 1 for _, gain in emitted)
    assert board.drain_sounds() == []


def test_pocket_sound_once_per_coin():
    board = Board()
    coin = 1
    board.discs[coin]['body'].position = (68, 68)
    board.active = True
    board.step()
    assert board.drain_sounds().count(('pocket', 1)) == 1
    board.step()
    assert ('pocket', 1) not in board.drain_sounds()


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 1.1])
def test_audio_volume_validation(value):
    with pytest.raises(ValueError):
        replace(Settings(), audio_sfx=value).validate()


def test_required_voice_configuration_and_secret_repr():
    with pytest.raises(ValueError):
        replace(Settings(), eleven_enabled=True).validate()
    settings = voice_settings()
    settings.validate()
    assert settings.eleven_key not in repr(settings)


def test_speech_cache_and_provider_contract(tmp_path):
    requests = []
    def transport(url, key, body):
        requests.append((url, key, body))
        return {'audio_base64': base64.b64encode(pcm('queen')).decode(),
                'alignment': {'characters': ['a'], 'character_start_times_seconds': [0],
                              'character_end_times_seconds': [.1]}}
    client = SpeechClient(voice_settings(), tmp_path, transport)
    wav, info = client.generate('Тест', 0)
    assert client.generate('Тест', 0) == (wav, info)
    assert len(requests) == 1 and 'voice-one/with-timestamps?output_format=pcm_24000' in requests[0][0]
    assert requests[0][2] == {'text': 'Тест', 'model_id': 'eleven_multilingual_v2'}
    assert wav.exists() and info['duration'] == .7
    for path in tmp_path.glob('*.json'):
        assert 'DO-NOT-LEAK' not in path.read_text(encoding='utf-8')


def test_failed_request_still_consumes_persistent_budget(tmp_path):
    calls = []
    def failure(*args):
        calls.append(1)
        raise RuntimeError('DO-NOT-LEAK')
    settings = voice_settings(eleven_max_chars=3)
    client = SpeechClient(settings, tmp_path, failure)
    with pytest.raises(SpeechError, match='^RuntimeError$'):
        client.generate('abc', 0)
    client = SpeechClient(settings, tmp_path, failure)
    with pytest.raises(SpeechError, match='BudgetExceeded'):
        client.generate('a', 1)
    assert len(calls) == 1


def test_budget_atomic_across_two_clients(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    s = voice_settings(eleven_max_chars=3)
    clients = [SpeechClient(s, tmp_path) for _ in range(2)]
    def reserve(client):
        try:
            client.reserve(3)
            return True
        except SpeechError:
            return False
    with ThreadPoolExecutor(2) as workers:
        assert sorted(workers.map(reserve, clients)) == [False, True]


@pytest.mark.parametrize('response', [
    {'audio_base64': 'bad'},
    {'audio_base64': base64.b64encode(b'1').decode()},
    {'audio_base64': base64.b64encode(pcm('shot')).decode(),
     'alignment': {'characters': ['a'], 'character_start_times_seconds': [0], 'character_end_times_seconds': [float('nan')]}},
])
def test_bad_audio_or_alignment_never_reaches_cache(tmp_path, response):
    client = SpeechClient(voice_settings(), tmp_path, lambda *args: response)
    with pytest.raises(SpeechError):
        client.generate('a', 0)
    assert not list(tmp_path.glob('*.wav'))


def test_disabled_tts_has_zero_network_requests(tmp_path):
    client = SpeechClient(Settings(), tmp_path, lambda *args: pytest.fail('Network called'))
    with pytest.raises(SpeechError, match='Disabled'):
        client.generate('abc', 0)


def test_worker_does_not_block_game_and_stops_queued_jobs():
    import threading
    entered, finish = threading.Event(), threading.Event()
    class Client:
        def generate(self, text, speaker):
            entered.set()
            finish.wait(2)
            return None
    worker = SpeechWorker(Client())
    assert worker.submit({'text': 'first', 'speaker': 0})
    assert entered.wait(1)
    assert worker.submit({'text': 'second', 'speaker': 1})
    worker.close()
    assert not worker.submit({'text': 'third', 'speaker': 0})
    finish.set()
    worker.thread.join(1)
    assert not worker.thread.is_alive() and worker.results.qsize() == 1


def test_commentary_uses_referee_not_pocket_count_for_victory():
    rules = NS(finished=False, winner=None, turn=2)
    text, sound = commentary(0, [(1, 'white')], Resolution(returned=[1]), rules)
    assert 'возвращено — 1' in text and 'выиграл' not in text
    rules.finished, rules.finish_reason = True, 'turn_safety_limit_aborted'
    text, sound = commentary(0, [(1, 'white')], Resolution(), rules)
    assert 'без победителя' in text
    rules.finished = False
    text, _ = commentary(1, [], Resolution(), rules)
    assert 'Авторская шутка' in text


def test_subtitle_rounding_overlap_and_early_exit():
    assert stamp(59.9996) == '00:01:00,000'
    text = subtitles([{'start': 1, 'end': 5, 'text': 'a'}, {'start': 2, 'end': 7, 'text': 'b'}], 3)
    assert '00:00:01,000 --> 00:00:02,000' in text
    assert '00:00:02,000 --> 00:00:03,000' in text
    with pytest.raises(ValueError):
        stamp(float('nan'))


def test_live_srt_and_stem_start_at_playback_not_request(tmp_path):
    now = [100.]
    settings = Settings()
    session = MediaSession(tmp_path / 'test.jsonl', settings, live=True, clock=lambda: now[0])
    path = tmp_path / 'voice.wav'
    path.write_bytes(wav_bytes(pcm('queen')))
    cue = {'time': 0., 'text': 'Сохранённый текст', 'speaker': 0}
    session.voices.append((cue, (path, {'duration': .7, 'alignment': None})))
    class Player:
        enabled = True
        voice = NS(get_busy=lambda: False)
        def speech(self, path):
            return .5
    now[0] = 103.
    session.tick(Player())
    now[0] = 104.
    session.close()
    srt = (session.directory / 'voice.srt').read_text(encoding='utf-8-sig')
    assert '00:00:03,000 --> 00:00:03,700' in srt
    with wave.open(str(session.directory / 'voice-1.wav')) as source:
        assert source.getnframes() == RATE * 4
        samples = array('h', source.readframes(source.getnframes()))
        assert not any(samples[:RATE * 3]) and any(samples[RATE * 3:])


def test_headless_media_uses_presentation_time_and_replay_seek(tmp_path):
    session = MediaSession(tmp_path / 'test.jsonl', Settings())
    session.update(1)
    session.sound('shot')
    session.update(2)
    session.completed(0, [], Resolution(), NS(finished=False, turn=1))
    session.update(7)
    session.close()
    manifest = json.loads((session.directory / 'manifest.json').read_text())
    assert manifest['duration'] == 7 and manifest['timebase'] == 'replay-presentation'
    player = NS(sound=lambda name: calls.append(name), stop_speech=lambda: None)
    replay, calls = ReplayMedia(tmp_path / 'test.replay.jsonl.gz'), []
    replay.seek(1.1, player)
    replay.advance(7, player)
    assert not calls and replay.latest
    replay.seek(0, player)
    replay.advance(1, player)
    assert calls == ['shot']


def test_sparse_mix_clips_and_keeps_silence(tmp_path):
    path = tmp_path / 'mix.wav'
    mix_stem(path, [(1, array('h', [30000, 30000]), 2)], 2)
    with wave.open(str(path)) as source:
        values = array('h', source.readframes(source.getnframes()))
    assert values[RATE] == 32767 and not any(values[:RATE])

def test_no_audio_and_replay_ignore_unconfigured_paid_tts(tmp_path):
    env = tmp_path / 'test.env'
    env.write_text('ELEVENLABS_ENABLED=true\n', encoding='utf-8')
    with pytest.raises(ValueError):
        Settings.load(env)
    assert not Settings.load(env, disable_audio=True).eleven_enabled
    assert not Settings.load(env, disable_voice=True).eleven_enabled


def test_background_export_does_not_wait_in_close(tmp_path, monkeypatch):
    import threading
    session = MediaSession(tmp_path / 'test.jsonl', Settings())
    entered, finish = threading.Event(), threading.Event()
    def export(duration):
        entered.set()
        finish.wait(2)
    monkeypatch.setattr(session, '_export', export)
    session.close(background=True)
    assert entered.wait(1) and session.closed and session.export_thread.is_alive()
    finish.set()
    session.wait_export()
    assert not session.export_thread.is_alive()


def test_audio_device_failure_keeps_text_export_available(monkeypatch):
    import os
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    import pygame as pg
    from audio import AudioPlayer
    pg.mixer.quit()
    def unavailable(*args, **kwargs):
        raise pg.error('no device')
    monkeypatch.setattr(pg.mixer, 'init', unavailable)
    player = AudioPlayer(pg, Settings())
    assert not player.enabled and player.warning
    assert player.sound('shot') == 0
    player.close()
