"""Exercise installed SDK serialization with a fake HTTP transport; no network."""
import json
import httpx2
from openai import OpenAI
from anthropic import Anthropic
from agents import decide, MOVE_SCHEMA
from engine import Match
from settings import Settings

MOVE = {'x': 380, 'angle': 270, 'power': 0.7, 'comment': 'SDK transport test'}
SETTINGS = Settings(mode='api', openai_model='mock-openai', anthropic_model='mock-claude')


def test_real_openai_sdk_serializes_and_parses():
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            'id': 'resp_mock', 'object': 'response', 'created_at': 0, 'status': 'completed',
            'model': 'mock-openai', 'output': [{'type': 'message', 'id': 'msg_mock',
                'role': 'assistant', 'status': 'completed', 'content': [{
                    'type': 'output_text', 'text': json.dumps(MOVE), 'annotations': []}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 12, 'total_tokens': 22}})
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        with OpenAI(api_key='test-not-a-real-key', http_client=http, max_retries=0) as client:
            result = decide(Match().state(), SETTINGS, client)
    assert result.move == MOVE and len(requests) == 1
    assert requests[0]['text']['format']['schema'] == MOVE_SCHEMA
    assert requests[0]['max_output_tokens'] == SETTINGS.max_output_tokens


def test_real_anthropic_sdk_serializes_and_parses():
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            'id': 'msg_mock', 'type': 'message', 'role': 'assistant', 'model': 'mock-claude',
            'content': [{'type': 'text', 'text': json.dumps(MOVE)}],
            'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 10, 'output_tokens': 12}})
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http:
        with Anthropic(api_key='test-not-a-real-key', http_client=http, max_retries=0) as client:
            result = decide(Match(first_player=1).state(), SETTINGS, client)
    assert result.move == MOVE and len(requests) == 1
    assert requests[0]['output_config']['format']['schema'] == MOVE_SCHEMA
    assert requests[0]['max_tokens'] == SETTINGS.max_output_tokens
