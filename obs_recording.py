"""OBS WebSocket v5, recording ownership and scoped recording directory."""
import base64
import hashlib
import json
from pathlib import Path
import time
import uuid
from websocket import create_connection


class OBSError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def authentication(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class OBSRecorder:
    def __init__(self, url='ws://127.0.0.1:4455', password='', timeout=5, connect=create_connection):
        self.owned = False
        self.old_directory = None
        self.old_scene = None
        self.record_path = None
        self.old_mutes = {}
        self.old_audio = {}
        self.audio_source = None
        self.record_started = None
        self.ws = None
        self.timeout = timeout
        try:
            self.ws = connect(url, timeout=timeout, http_no_proxy=['localhost', '127.0.0.1', '::1'])
            hello = json.loads(self.ws.recv())
            if hello.get('op') != 0:
                raise OBSError('OBS handshake: expected Hello')
            data = {'rpcVersion': 1, 'eventSubscriptions': 0}
            auth = hello.get('d', {}).get('authentication')
            if auth:
                data['authentication'] = authentication(password, auth['salt'], auth['challenge'])
            self.ws.send(json.dumps({'op': 1, 'd': data}))
            if json.loads(self.ws.recv()).get('op') != 2:
                raise OBSError('OBS authentication failed')
        except Exception as exc:
            self.close()
            raise OBSError('Cannot connect/authenticate with OBS: ' + type(exc).__name__) from None

    def request(self, kind, data=None):
        request_id = uuid.uuid4().hex
        self.ws.send(json.dumps({'op': 6, 'd': {'requestType': kind, 'requestId': request_id, 'requestData': data or {}}}))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            reply = json.loads(self.ws.recv())
            if reply.get('op') == 7 and reply.get('d', {}).get('requestId') == request_id:
                body = reply['d']
                if not body['requestStatus']['result']:
                    code = body['requestStatus'].get('code')
                    raise OBSError(kind + ' failed (code ' + str(code) + ')', code)
                return body.get('responseData', {})
        raise OBSError(kind + ' response timed out')

    def setup_window_scene(self, scene='Carrom AI Showdown', window_title='Carrom AI Showdown', game_audio=False):
        if self.request('GetStreamStatus').get('outputActive') or self.request('GetRecordStatus').get('outputActive'):
            raise OBSError('OBS output is already active; scene setup cannot run')
        scenes = self.request('GetSceneList')
        if scene not in [s['sceneName'] for s in scenes['scenes']]:
            self.request('CreateScene', {'sceneName': scene})
        source = scene + ' / Window'
        inputs = self.request('GetInputList')['inputs']
        if source not in [item['inputName'] for item in inputs]:
            self.request('CreateInput', {'sceneName': scene, 'inputName': source, 'inputKind': 'window_capture',
                                         'inputSettings': {'cursor': False}, 'sceneItemEnabled': True})
        windows = self.request('GetInputPropertiesListPropertyItems', {'inputName': source, 'propertyName': 'window'})
        matching = [item for item in windows['propertyItems']
                    if item.get('itemEnabled', True) and window_title in item.get('itemName', '')]
        if len(matching) != 1:
            raise OBSError('OBS needs exactly one matching Carrom window; close duplicate game windows')
        self.request('SetInputSettings', {'inputName': source, 'inputSettings': {'window': matching[0]['itemValue'], 'cursor': False, 'capture_audio': False}, 'overlay': True})
        item_id = self.request('GetSceneItemId', {'sceneName': scene, 'sourceName': source})['sceneItemId']
        video = self.request('GetVideoSettings')
        self.request('SetSceneItemTransform', {'sceneName': scene, 'sceneItemId': item_id,
                     'sceneItemTransform': {'positionX': 0, 'positionY': 0, 'alignment': 5,
                         'boundsType': 'OBS_BOUNDS_SCALE_INNER', 'boundsWidth': video['baseWidth'],
                         'boundsHeight': video['baseHeight'], 'boundsAlignment': 0}})
        if game_audio:
            self.setup_game_audio(scene, matching[0]['itemValue'])
        return scene

    def setup_game_audio(self, scene, window):
        if 'wasapi_process_output_capture' not in self.request('GetInputKindList')['inputKinds']:
            raise OBSError('OBS Application Audio Capture is unavailable; use Windows 11 OBS')
        source = scene + ' / Game Audio'
        inputs = self.request('GetInputList')['inputs']
        existing = [item for item in inputs if item['inputName'] == source]
        if existing and existing[0]['inputKind'] != 'wasapi_process_output_capture':
            raise OBSError('Game Audio source has an incompatible type')
        if not existing:
            self.request('CreateInput', {'sceneName': scene, 'inputName': source,
                         'inputKind': 'wasapi_process_output_capture',
                         'inputSettings': {'window': window, 'priority': 0}, 'sceneItemEnabled': True})
        else:
            self.old_audio['settings'] = self.request('GetInputSettings', {'inputName': source})['inputSettings']
        self.audio_source = source
        self.old_audio['mute'] = self.request('GetInputMute', {'inputName': source})['inputMuted']
        self.old_audio['tracks'] = self.request('GetInputAudioTracks', {'inputName': source})['inputAudioTracks']
        self.old_audio['monitor'] = self.request('GetInputAudioMonitorType', {'inputName': source})['monitorType']
        self.old_audio['volume'] = self.request('GetInputVolume', {'inputName': source})['inputVolumeMul']
        self.request('SetInputSettings', {'inputName': source,
                     'inputSettings': {'window': window, 'priority': 0}, 'overlay': True})
        self.request('SetInputMute', {'inputName': source, 'inputMuted': False})
        self.request('SetInputVolume', {'inputName': source, 'inputVolumeMul': 1})
        self.request('SetInputAudioMonitorType', {'inputName': source, 'monitorType': 'OBS_MONITORING_TYPE_NONE'})
        self.request('SetInputAudioTracks', {'inputName': source,
                     'inputAudioTracks': {str(i): i in (1, 2) for i in range(1, 7)}})
        # Routing is configured; recording track selection is an OBS output-profile setting.

    def start(self, directory=None, scene=None):
        if self.request('GetRecordStatus').get('outputActive'):
            raise OBSError('OBS is already recording; refusing to take ownership')
        if scene and self.request('GetStreamStatus').get('outputActive'):
            raise OBSError('OBS is streaming; refusing to switch its scene')
        try:
            if directory:
                directory = Path(directory).resolve()
                directory.mkdir(parents=True, exist_ok=True)
                self.old_directory = self.request('GetRecordDirectory')['recordDirectory']
                self.request('SetRecordDirectory', {'recordDirectory': str(directory)})
            if scene:
                self.old_scene = self.request('GetCurrentProgramScene')['currentProgramSceneName']
                self.request('SetCurrentProgramScene', {'sceneName': scene})
                # Capture only the game process; avoid duplicated desktop audio and microphone.
                names = set(v for v in self.request('GetSpecialInputs').values() if isinstance(v, str) and v)
                for name in names:
                    self.old_mutes[name] = self.request('GetInputMute', {'inputName': name})['inputMuted']
                    self.request('SetInputMute', {'inputName': name, 'inputMuted': True})
            self.request('StartRecord')
            self.owned = True
            self.record_started = time.monotonic()
        except Exception:
            self.restore()
            raise

    def restore(self):
        if self.audio_source:
            source = self.audio_source
            fields = {'settings': ('SetInputSettings', 'inputSettings'), 'mute': ('SetInputMute', 'inputMuted'),
                      'tracks': ('SetInputAudioTracks', 'inputAudioTracks'),
                      'monitor': ('SetInputAudioMonitorType', 'monitorType'), 'volume': ('SetInputVolume', 'inputVolumeMul')}
            for name, value in list(self.old_audio.items()):
                request, field = fields[name]
                self.request(request, {'inputName': source, field: value})
                del self.old_audio[name]
            self.audio_source = None
        for name, muted in list(self.old_mutes.items()):
            self.request('SetInputMute', {'inputName': name, 'inputMuted': muted})
            del self.old_mutes[name]
        if self.old_scene is not None:
            self.request('SetCurrentProgramScene', {'sceneName': self.old_scene})
            self.old_scene = None
        if self.old_directory is not None:
            # StopRecord can reply while the frontend is still finalizing its output.
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    self.request('SetRecordDirectory', {'recordDirectory': self.old_directory})
                    self.old_directory = None
                    break
                except OBSError as exc:
                    if exc.code != 500 or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)

    def stop(self):
        if self.owned:
            try:
                response = self.request('StopRecord')
                self.record_path = response.get('outputPath')
                self.owned = False
            finally:
                if not self.owned:
                    self.restore()
        return self.record_path

    def close(self):
        if self.ws is not None:
            try:
                self.stop()
                if not self.owned:
                    self.restore()
            finally:
                self.ws.close()
                self.ws = None
