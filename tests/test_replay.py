import gzip
import json
import pytest
from replay import Replay, Recorder, inspect_replay
from runner import run_headless
from engine import Match
from settings import Settings


def test_record_load_seek_and_exact_final_state(tmp_path):
    result = run_headless(Settings(), tmp_path, max_turns=2)
    replay = Replay(result['replay'])
    assert replay.complete and len(replay.frames) > 10
    assert replay.summary['scores'] == result['scores']
    assert replay.frames[-1]['state']['rules']['finished']
    assert replay.seek(-1) == 0
    assert replay.seek(replay.duration + 100) == len(replay.frames) - 1
    assert replay.duration > 0


def test_frame_positions_record_striker_velocity(tmp_path):
    match = Match()
    recorder = Recorder(tmp_path / 'data.gz', match.state(), 'test', 'demo')
    match.shoot({'x': 380, 'angle': 270, 'power': 0.75, 'comment': ''})
    recorder.frame(match, 0)
    recorder.close()
    replay = Replay(recorder.path)
    striker = next(d for d in replay.frames[0]['discs'] if d['id'] == -1)
    assert striker['y'] == 665 and striker['vy'] == pytest.approx(-787.5)


def test_tampered_frame_rejected(tmp_path):
    match = Match()
    path = tmp_path / 'data.gz'
    recorder = Recorder(path, match.state(), 'test', 'demo')
    recorder.frame(match, 0)
    recorder.close()
    with gzip.open(path, 'rt', encoding='utf-8') as file:
        lines = file.readlines()
    frame = json.loads(lines[1])
    frame['discs'][0]['x'] += 1
    lines[1] = json.dumps(frame) + '\n'
    with gzip.open(path, 'wt', encoding='utf-8') as file:
        file.writelines(lines)
    with pytest.raises(ValueError, match='checksum'):
        Replay(path)


def test_incomplete_replay_rejected(tmp_path):
    path = tmp_path / 'bad.gz'
    with gzip.open(path, 'wt', encoding='utf-8') as file:
        file.write('{}\n')
    with pytest.raises(ValueError):
        Replay(path)


def test_replay_ui_does_not_call_agent(tmp_path, monkeypatch):
    result = run_headless(Settings(), tmp_path / 'match', max_turns=1)
    def forbidden(*args, **kwargs):
        raise AssertionError('Replay called a live agent')
    monkeypatch.setattr('agents.decide', forbidden)
    monkeypatch.setattr('runner.Controller', forbidden)
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    from replay_ui import ReplayApp
    app = ReplayApp(result['replay'], directory=tmp_path / 'playback')
    app.run(frames=3, screenshot=tmp_path / 'replay.png')
    assert (tmp_path / 'replay.png').stat().st_size > 1000
    assert not (tmp_path / 'playback').exists()
