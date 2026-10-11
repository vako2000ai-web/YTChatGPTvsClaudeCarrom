import importlib.util
from pathlib import Path
import httpx2 as httpx
import anthropic
import pytest


@pytest.fixture
def script():
    path = Path(__file__).resolve().parents[1] / 'Keys/TestAPI.py'
    spec = importlib.util.spec_from_file_location('carrom_test_api', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(tmp_path, text='ANTHROPIC_API_KEY=sk-ant-fake\n'):
    path = tmp_path / '.env'
    path.write_text(text, encoding='utf-8')
    return path


def test_dry_run_cannot_send_request(script, tmp_path, capsys):
    path = config(tmp_path)
    assert script.main(['--config', str(path), '--dry-run'],
                       client_factory=lambda **kwargs: pytest.fail('Live client created')) == 0
    output = capsys.readouterr().out
    assert 'claude-opus-5-5' in output and 'sk-ant-fake' not in output


def test_one_messages_request_with_real_sdk_on_mock_transport(script, tmp_path, capsys):
    import json
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url == 'https://api.anthropic.com/v1/messages'
        body = json.loads(request.content)
        assert body['model'] == 'claude-sonnet-5-5' and body['max_tokens'] == 1024
        assert body['messages'] == [{'role': 'user', 'content': 'Hello, world'}]
        return httpx.Response(200, json={'id': 'msg_test', 'type': 'message', 'role': 'assistant',
            'model': 'claude-sonnet-5-5', 'content': [{'type': 'text', 'text': 'Hello!'}],
            'stop_reason': 'end_turn', 'stop_sequence': None, 'usage': {'input_tokens': 5, 'output_tokens': 3}})
    def client(**kwargs):
        assert kwargs['max_retries'] == 0 and kwargs['timeout'] == 20
        return anthropic.Anthropic(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    path = config(tmp_path)
    assert script.main(['--config', str(path), '--model', 'claude-sonnet-5-5'], client_factory=client) == 0
    output = capsys.readouterr().out
    assert len(requests) == 1 and 'Hello!' in output and 'sk-ant-fake' not in output


def test_http_error_has_no_retries_or_secret_output(script, tmp_path, capsys):
    count = []
    def handler(request):
        count.append(1)
        return httpx.Response(401, json={'type': 'error', 'error': {'type': 'authentication_error',
                               'message': 'Secret error detail sk-ant-fake'}})
    def client(**kwargs):
        return anthropic.Anthropic(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert script.main(['--config', str(config(tmp_path))], client_factory=client) == 1
    output = capsys.readouterr().err
    assert len(count) == 1 and 'HTTP 401' in output and 'sk-ant-fake' not in output and 'Secret error detail' not in output


@pytest.mark.parametrize('text', ['', 'ANTHROPIC_API_KEY=sk-proj-fake\n',
                                'ANTHROPIC_API_KEY=sk-ant-fake\nANTHROPIC_MODEL=sk-ant-secret\n'])
def test_bad_configuration_fails_before_network(script, tmp_path, text, capsys):
    path = config(tmp_path, text)
    assert script.main(['--config', str(path)],
                       client_factory=lambda **kwargs: pytest.fail('Network attempted')) == 2
    assert 'sk-ant-secret' not in capsys.readouterr().err


def test_root_env_is_independent_of_current_directory(script, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert script.DEFAULT_ENV == Path(script.__file__).resolve().parents[1] / '.env'


@pytest.mark.parametrize('status,message,expected', [
    (400, 'Your credit balance is too low to access the Anthropic API. sk-ant-fake', 'недостаточно API-кредитов'),
    (400, 'Workspace spend limit reached sk-ant-fake', 'лимит расходов'),
    (400, 'The model is not available sk-ant-fake', 'отклонил выбранную модель'),
    (400, 'max_tokens invalid sk-ant-fake', 'отклонил параметры'),
    (400, 'Unrecognized failure sk-ant-fake', 'не распознана'),
    (402, 'Payment failed sk-ant-fake', 'API-биллинг'),
])
def test_error_diagnosis_through_sdk_without_raw_response(script, tmp_path, capsys, status, message, expected):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'type': 'error', 'error': {
            'type': 'invalid_request_error', 'message': message}})
    def client(**kwargs):
        return anthropic.Anthropic(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert script.main(['--config', str(config(tmp_path))], client_factory=client) == 1
    captured = capsys.readouterr()
    assert len(requests) == 1 and f'HTTP {status}' in captured.err and expected in captured.err
    assert 'sk-ant-fake' not in captured.out + captured.err
    assert message not in captured.err


@pytest.mark.parametrize('body', ['sk-ant-fake', {'error': 'sk-ant-fake'},
                                  {'error': {'message': ['sk-ant-fake']}}])
def test_unexpected_error_body_has_safe_fallback(script, body):
    from types import SimpleNamespace
    hint = script.error_hint(SimpleNamespace(status_code=400, body=body))
    assert 'не распознана' in hint and 'sk-ant-fake' not in hint


def test_prepared_script_matches_installed_script(script):
    path = Path(script.__file__)
    assert path.read_bytes() == path.with_name('TestAPI.fixed.py').read_bytes()
