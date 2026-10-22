"""A Veriphex agent that carries its own small AI model, run on the CPU with llama.cpp.

start.sh starts llama.cpp's server on 127.0.0.1:8081 inside the sealed space, then runs this.
The agent lists its tools from VERIPHEX_MCP_URL (the only address it may reach), lets the model
choose tool calls through llama.cpp's OpenAI-compatible chat API, makes each call through
Veriphex, and writes the model's final answer to VERIPHEX_RESULT_FILE.

The model never leaves the sealed space, so its use is not counted by Veriphex. Declare it on the
form (its name and rough size) so the person and the admin know it is there.
"""
import json
import os
import sys
from pathlib import Path

import requests

MCP_URL = os.environ['VERIPHEX_MCP_URL']
LLAMA_URL = os.environ.get('LLAMA_URL', 'http://127.0.0.1:8081/v1/chat/completions')
MAX_STEPS = 20


class Mcp:
    """The smallest MCP client over streamable HTTP that this agent needs."""

    def __init__(self, url):
        self.url, self.session, self.next_id = url, None, 0

    def call(self, method, params=None):
        self.next_id += 1
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        resp = requests.post(self.url, json={'jsonrpc': '2.0', 'id': self.next_id, 'method': method,
                                             'params': params or {}}, headers=headers, timeout=300)
        resp.raise_for_status()
        self.session = resp.headers.get('Mcp-Session-Id', self.session)
        text = resp.text
        if resp.headers.get('Content-Type', '').startswith('text/event-stream'):
            text = next(l[5:] for l in text.splitlines() if l.startswith('data:'))
        body = json.loads(text)
        if 'error' in body:
            raise RuntimeError(body['error'].get('message'))
        return body['result']

    def notify(self, method):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        requests.post(self.url, json={'jsonrpc': '2.0', 'method': method}, headers=headers, timeout=60)


def main():
    job = json.loads(Path(os.environ['VERIPHEX_TASK_FILE']).read_text(encoding='utf-8'))
    mcp = Mcp(MCP_URL)
    mcp.call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                            'clientInfo': {'name': 'veriphex-builtin-model-agent', 'version': '0'}})
    mcp.notify('notifications/initialized')
    tools = [{'type': 'function', 'function': {'name': t['name'], 'description': t.get('description', ''),
                                               'parameters': t.get('inputSchema') or {'type': 'object'}}}
             for t in mcp.call('tools/list')['tools']]
    messages = [{'role': 'system', 'content': 'Do the task with the tools you have, then answer in plain sentences.'},
                {'role': 'user', 'content': job['task']}]
    answer = ''
    for _ in range(MAX_STEPS):
        reply = requests.post(LLAMA_URL, json={'messages': messages, 'tools': tools}, timeout=900).json()
        message = reply['choices'][0]['message']
        messages.append(message)
        calls = message.get('tool_calls') or []
        if not calls:
            answer = message.get('content') or ''
            break
        for call in calls:
            args = json.loads(call['function'].get('arguments') or '{}')
            result = mcp.call('tools/call', {'name': call['function']['name'], 'arguments': args})
            text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
            messages.append({'role': 'tool', 'tool_call_id': call.get('id', ''), 'content': text})
    Path(os.environ['VERIPHEX_RESULT_FILE']).write_text(answer, encoding='utf-8')
    return 0 if answer else 1


if __name__ == '__main__':
    sys.exit(main())
