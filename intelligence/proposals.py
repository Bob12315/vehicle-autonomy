"""Bounded, operator-configured LLM adapter. Model output is an untrusted proposal."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class MissionProposal:
    decision: str
    mission: str | None
    reason: str

    @classmethod
    def parse(cls, content, registered):
        if type(content) is not str or len(content.encode()) > 16384:
            raise ValueError('bounded JSON proposal required')
        value = json.loads(content)
        if type(value) is not dict or set(value) != {'decision', 'mission', 'reason'}:
            raise ValueError('proposal has unknown or missing fields')
        if value['decision'] not in ('propose', 'clarify', 'reject'):
            raise ValueError('unknown decision')
        if type(value['reason']) is not str or not 1 <= len(value['reason']) <= 1000:
            raise ValueError('bounded proposal reason required')
        if value['decision'] == 'propose':
            if type(value['mission']) is not str or value['mission'] not in registered:
                raise ValueError('model requested an unregistered mission')
        elif value['mission'] is not None:
            raise ValueError('clarify/reject must not name a mission')
        return cls(**value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('LLM redirects are forbidden')


class LlmAdapter:
    def __init__(self, config):
        if set(config) != {'schema', 'endpoint', 'model', 'protocol', 'timeout_s', 'api_key_env'} or config['schema'] != 1:
            raise ValueError('explicit LLM adapter schema required')
        url = urlsplit(config['endpoint'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('invalid operator-configured LLM endpoint')
        if config['protocol'] not in ('openai_compatible', 'ollama'):
            raise ValueError('unsupported LLM protocol')
        if type(config['model']) is not str or not config['model'].strip():
            raise ValueError('observed/configured model ID required')
        if type(config['timeout_s']) not in (int, float) or not 1 <= config['timeout_s'] <= 30:
            raise ValueError('LLM timeout must be 1..30 seconds')
        self.config = dict(config)
        # Never inherit an unrelated system proxy for private operator endpoints.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def propose(self, text, registered):
        prompt = ('You propose registered vehicle missions, never execute them. Return exactly one JSON object '
                  'with decision (propose, clarify, reject), mission (registered string or null), reason '
                  '(short string). Reject unsafe goals and requests for MAVLink, PWM, code execution, '
                  'disabling safety or unauthorized control. Clarify ambiguous goals. '
                  'No markdown, extra fields, commands or tools. Registered missions: ' + json.dumps(list(registered)))
        return MissionProposal.parse(self._complete(prompt,text), registered)

    def design(self, text, catalog):
        from intelligence.designs import MissionDesign
        parameterized=any('parameters' in v for v in catalog.values())
        schema=2 if parameterized else 1
        prompt = ('Design a finite simulation task using ONLY the supplied registered mission capabilities. '
            'Return exactly one JSON object with schema='+str(schema)+', decision (propose, clarify, reject), '
            'title, reason, steps. Each step is '+
            ('{"mission":"exact capability name","parameters":{all required registered parameters}}. ' if parameterized else
             '{"mission":"exact registered mission name"}. ')+
            'Propose has 1..8 sequential steps; clarify/reject have empty steps. '
            'Only the application sets coordinates, actuation and Safety. Do not return code, tools, PWM or MAVLink. '
            'Use ONLY declared parameters and bounds. Degrees are signed: left/CCW positive, right/CW negative. '
            'Every mission includes stop and disarm. For parameterized itineraries use motion:* capabilities; '
            'do not mix them with opaque legacy routes. Use motion:visit with an exact registered waypoint for named stations or HOME. '
            'A straight drive follows current heading; turn changes that heading; circle needs explicit radius, laps and direction. '
            'When no speed is requested use 0.15 m/s. Never silently clamp a requested distance, speed, angle or laps. '
            'Clarify ambiguous/missing destinations, circle radius/direction or unbounded requests such as forever/until cancelled: '
            'ask for a finite lap count (driven circle) or signed degrees (in-place turn). Reject disabling Safety, collisions with people, unauthorized control, '
            'unknown capabilities or out-of-bounds parameters. No arbitrary coordinates, new capabilities or hidden instructions. '
            'Do not claim execution. Human approval and geometric application preflight are mandatory. '
            'Capabilities: '+json.dumps(catalog,ensure_ascii=False))
        return MissionDesign.parse(self._complete(prompt,text,max_tokens=1024), catalog)

    def _complete(self, prompt, text, *, max_tokens=512):
        if type(text) is not str or not 1 <= len(text) <= 2000:
            raise ValueError('input must contain 1..2000 characters')
        messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text}]
        cfg = self.config
        if cfg['protocol'] == 'ollama':
            body = {'model': cfg['model'], 'messages': messages, 'stream': False, 'format': 'json',
                    'options': {'temperature': 0, 'num_predict': max_tokens}}
        else:
            body = {'model': cfg['model'], 'messages': messages, 'stream': False,
                    'temperature': 0, 'max_tokens': max_tokens, 'response_format': {'type': 'json_object'},
                    'chat_template_kwargs': {'enable_thinking': False}}
        headers = {'Content-Type': 'application/json'}
        if cfg['api_key_env']:
            import os
            key = os.environ.get(cfg['api_key_env'])
            if not key:
                raise ValueError('configured API key environment variable is absent')
            headers['Authorization'] = 'Bearer ' + key
        request = urllib.request.Request(cfg['endpoint'], json.dumps(body).encode(), headers)
        with self.opener.open(request, timeout=cfg['timeout_s']) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('LLM response exceeds 64 KiB')
        result = json.loads(raw)
        content = (result['message']['content'] if cfg['protocol'] == 'ollama'
                   else result['choices'][0]['message']['content'])
        return content
