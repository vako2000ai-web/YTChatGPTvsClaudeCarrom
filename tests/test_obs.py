import json
import pytest
from obs_recording import OBSRecorder, OBSError, authentication


class Socket:
    def __init__(self, active=False, fail_start=False):
        self.active = active
        self.fail_start = fail_start
        self.closed = False
        self.messages, self.types = [], []
        self.replies = [{'op': 0, 'd': {'rpcVersion': 1,
            'authentication': {'salt': 'test-salt', 'challenge': 'test-challenge'}}}]

    def send(self, text):
        data = json.loads(text)
        self.messages.append(data)
        if data['op'] == 1:
            self.replies.append({'op': 2, 'd': {'negotiatedRpcVersion': 1}})
        else:
            name = data['d']['requestType']
            self.types.append(name)
            responses = {'GetRecordStatus': {'outputActive': self.active},
                         'GetRecordDirectory': {'recordDirectory': 'original-directory'},
                         'GetCurrentProgramScene': {'currentProgramSceneName': 'Original Scene'},
                         'GetStreamStatus': {'outputActive': False},
                         'StopRecord': {'outputPath': 'match.mkv'}}
            self.replies.append({'op': 7, 'd': {'requestId': data['d']['requestId'],
                'requestStatus': {'result': not (name == 'StartRecord' and self.fail_start), 'code': 500},
                'responseData': responses.get(name, {})}})

    def recv(self):
        return json.dumps(self.replies.pop(0))

    def close(self):
        self.closed = True


def client(socket):
    return OBSRecorder(password='fake-password', connect=lambda *a, **k: socket)


def test_obs_v5_authentication_and_record_lifecycle(tmp_path):
    socket = Socket()
    recorder = client(socket)
    assert socket.messages[0]['d']['authentication'] == authentication('fake-password', 'test-salt', 'test-challenge')
    recorder.start(tmp_path, 'Carrom')
    assert recorder.owned
    assert recorder.stop() == 'match.mkv'
    recorder.close()
    assert socket.types.count('StartRecord') == socket.types.count('StopRecord') == 1
    assert socket.closed
    assert socket.types[-2:] == ['SetCurrentProgramScene', 'SetRecordDirectory']
    assert 'fake-password' not in json.dumps(socket.messages)


def test_existing_recording_is_never_stopped():
    socket = Socket(active=True)
    recorder = client(socket)
    with pytest.raises(OBSError, match='already recording'):
        recorder.start()
    recorder.close()
    assert 'StartRecord' not in socket.types and 'StopRecord' not in socket.types


def test_start_failure_restores_scene_and_directory(tmp_path):
    socket = Socket(fail_start=True)
    recorder = client(socket)
    with pytest.raises(OBSError):
        recorder.start(tmp_path, 'Carrom')
    recorder.close()
    assert 'StopRecord' not in socket.types
    assert socket.types[-2:] == ['SetCurrentProgramScene', 'SetRecordDirectory']


def test_close_without_start_has_no_recording_side_effect():
    socket = Socket()
    client(socket).close()
    assert socket.types == []


def test_finalizing_output_retries_directory_restore(tmp_path, monkeypatch):
    socket = Socket()
    recorder = client(socket)
    recorder.start(tmp_path, 'Carrom')
    original = recorder.request
    attempts = []
    def request(kind, data=None):
        if kind == 'SetRecordDirectory' and data['recordDirectory'] == 'original-directory':
            attempts.append(kind)
            if len(attempts) == 1:
                raise OBSError('output still finalizing', 500)
        return original(kind, data)
    recorder.request = request
    monkeypatch.setattr('obs_recording.time.sleep', lambda _: None)
    assert recorder.stop() == 'match.mkv'
    assert len(attempts) == 2 and recorder.old_directory is None
    recorder.close()
