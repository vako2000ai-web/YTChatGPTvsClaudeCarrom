import gzip
import hashlib
import json
import pytest
from engine import Match
from replay import Replay, Recorder, canonical


@pytest.mark.parametrize('field,value', [('discs', [None]), ('discs', [{'id': []}]), ('state', []),
                                       ('time', float('inf'))])
def test_malformed_frame_is_rejected_as_value_error(tmp_path, field, value):
    path = tmp_path / 'bad.gz'
    recorder = Recorder(path, Match().state(), 'test', 'demo')
    recorder.frame(Match(), 0)
    recorder.close()
    with gzip.open(path, 'rt', encoding='utf-8') as file:
        records = [json.loads(line) for line in file]
    frame = records[1]
    frame.pop('checksum')
    frame[field] = value
    if field == 'time':
        frame['checksum'] = 'invalid'
    else:
        frame['checksum'] = hashlib.sha256(canonical(frame).encode()).hexdigest()
    with gzip.open(path, 'wt', encoding='utf-8') as file:
        for item in records:
            file.write(json.dumps(item) + '\n')
    with pytest.raises(ValueError):
        Replay(path)


def test_no_frames_may_follow_footer(tmp_path):
    path = tmp_path / 'bad.gz'
    recorder = Recorder(path, Match().state(), 'test', 'demo')
    recorder.frame(Match(), 0)
    recorder.close()
    with gzip.open(path, 'rt', encoding='utf-8') as file:
        records = list(file)
    with gzip.open(path, 'at', encoding='utf-8') as file:
        file.write(records[1])
    with pytest.raises(ValueError, match='after replay footer'):
        Replay(path)


def test_replay_uses_stored_geometry_instead_of_current_factory(tmp_path, monkeypatch):
    path = tmp_path / 'good.gz'
    match = Match(ruleset='icf')
    recorder = Recorder(path, match.state(), 'test', 'demo')
    recorder.frame(match, 0)
    recorder.close()
    from replay_ui import ReplayController
    monkeypatch.setattr('board.official_geometry', lambda: None)
    replay = Replay(path)
    controller = ReplayController(replay)
    assert controller.match.board.geometry.coin_radius == replay.frames[0]['state']['board']['coin_radius']
