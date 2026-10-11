import pytest
from obs_recording import OBSRecorder, OBSError


def fake(existing=True, unsupported=False, fail=None):
    recorder = object.__new__(OBSRecorder)
    recorder.old_audio = {}
    recorder.audio_source = None
    recorder.old_mutes = {}
    recorder.old_scene = recorder.old_directory = None
    recorder.calls = []
    def request(name, data=None):
        recorder.calls.append((name, data))
        if name == fail:
            raise OBSError('failure')
        return {
            'GetInputKindList': {'inputKinds': [] if unsupported else ['wasapi_process_output_capture']},
            'GetInputList': {'inputs': [{'inputName': 'Test / Game Audio', 'inputKind': 'wasapi_process_output_capture'}] if existing else []},
            'GetInputSettings': {'inputSettings': {'window': 'old', 'priority': 1}},
            'GetInputMute': {'inputMuted': True},
            'GetInputAudioTracks': {'inputAudioTracks': {'1': True, '2': False}},
            'GetInputAudioMonitorType': {'monitorType': 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT'},
            'GetInputVolume': {'inputVolumeMul': .5},
        }.get(name, {})
    recorder.request = request
    return recorder


def test_application_audio_routes_only_game_and_restores_existing_settings():
    recorder = fake()
    recorder.setup_game_audio('Test', 'Carrom:title:exe')
    tracks = [data for name, data in recorder.calls if name == 'SetInputAudioTracks'][0]
    assert tracks['inputAudioTracks'] == {'1': True, '2': True, '3': False, '4': False, '5': False, '6': False}
    assert ('SetInputSettings', {'inputName': 'Test / Game Audio', 'inputSettings': {'window': 'Carrom:title:exe', 'priority': 0}, 'overlay': True}) in recorder.calls
    recorder.restore()
    assert recorder.audio_source is None and not recorder.old_audio
    assert ('SetInputMute', {'inputName': 'Test / Game Audio', 'inputMuted': True}) in recorder.calls
    assert ('SetInputVolume', {'inputName': 'Test / Game Audio', 'inputVolumeMul': .5}) in recorder.calls
    assert ('SetInputSettings', {'inputName': 'Test / Game Audio', 'inputSettings': {'window': 'old', 'priority': 1}}) in recorder.calls


def test_unsupported_capture_fails_before_mutations():
    recorder = fake(unsupported=True)
    with pytest.raises(OBSError, match='unavailable'):
        recorder.setup_game_audio('Test', 'window')
    assert len(recorder.calls) == 1


def test_partial_setup_failure_can_be_restored():
    recorder = fake(fail='SetInputAudioTracks')
    with pytest.raises(OBSError):
        recorder.setup_game_audio('Test', 'window')
    original = recorder.request
    recorder.request = lambda name, data=None: {} if name == 'SetInputAudioTracks' else original(name, data)
    recorder.restore()
    assert recorder.audio_source is None and not recorder.old_audio


def scene_client(windows):
    recorder = fake()
    def request(name, data=None):
        recorder.calls.append((name, data))
        return {
            'GetStreamStatus': {'outputActive': False},
            'GetRecordStatus': {'outputActive': False},
            'GetSceneList': {'scenes': [{'sceneName': 'Test'}]},
            'GetInputList': {'inputs': [{'inputName': 'Test / Window'}]},
            'GetInputPropertiesListPropertyItems': {'propertyItems': windows},
            'GetSceneItemId': {'sceneItemId': 1},
            'GetVideoSettings': {'baseWidth': 1920, 'baseHeight': 1080},
        }.get(name, {})
    recorder.request = request
    return recorder


def test_stale_disabled_obs_window_does_not_block_new_exe():
    recorder = scene_client([
        {'itemName': 'Carrom AI Showdown', 'itemValue': 'old:python.exe', 'itemEnabled': False},
        {'itemName': 'Carrom AI Showdown', 'itemValue': 'new:game.exe', 'itemEnabled': True}])
    recorder.setup_window_scene('Test')
    settings = [data for kind, data in recorder.calls if kind == 'SetInputSettings'][0]
    assert settings['inputSettings']['window'] == 'new:game.exe'


def test_two_active_game_windows_require_disambiguation():
    recorder = scene_client([
        {'itemName': 'Carrom AI Showdown', 'itemValue': 'one', 'itemEnabled': True},
        {'itemName': 'Carrom AI Showdown', 'itemValue': 'two', 'itemEnabled': True}])
    with pytest.raises(OBSError, match='exactly one'):
        recorder.setup_window_scene('Test')
