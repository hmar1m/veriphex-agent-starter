#!/usr/bin/env python3
"""The practice door: a stand-in for Veriphex's door, on your own computer.

In the sealed space an agent reaches the world through exactly two addresses: `POST /mcp` for its
tools and `POST /model/anthropic/v1/messages` for the AI model. This server answers both locally,
so you can run your agent before you submit it:

- `/mcp` lists the tools in tools.txt and answers each tools/call with an echo of what was asked.
  A call to a tool tools.txt does not declare is refused, as Veriphex would refuse it.
- `/model/anthropic/v1/messages` forwards to Anthropic only if you set PRACTICE_ANTHROPIC_API_KEY
  here, on your computer; otherwise it answers with a short canned reply.
- Anything else, including a proxy request or CONNECT for another host, is refused and recorded
  as a direct internet attempt.

It prints one `PRACTICE {json}` line per request. Save them and check them:
    python3 practice_door.py --tools ../template-python/tools.txt | tee practice.log
    veriphex-check --practice-log practice.log --tools ../template-python/tools.txt

Needs flask and requests.
"""
import argparse
import json
import os
import sys
import uuid

from flask import Flask, Response, request

LOCAL_HOSTS = {'127.0.0.1', 'localhost', 'host.docker.internal', '10.200.0.1', '[::1]'}
ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
PASS_HEADERS = ('anthropic-version', 'anthropic-beta', 'content-type', 'accept')


def read_tools(path):
    names = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.split('#', 1)[0].strip()
            if line:
                names.append(line.split()[0])
    return names


def record(kind, out=None, **fields):
    print('PRACTICE ' + json.dumps({'kind': kind, **fields}, sort_keys=True), file=out or sys.stdout, flush=True)


def _canned_message(model, text):
    return {'id': 'msg_practice_' + uuid.uuid4().hex[:12], 'type': 'message', 'role': 'assistant',
            'model': model, 'content': [{'type': 'text', 'text': text}],
            'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 1, 'output_tokens': 1}}


def _canned_stream(model, text):
    message = _canned_message(model, '')
    message['content'] = []
    message['stop_reason'] = None
    events = [
        ('message_start', {'type': 'message_start', 'message': message}),
        ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                 'content_block': {'type': 'text', 'text': ''}}),
        ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                 'delta': {'type': 'text_delta', 'text': text}}),
        ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
        ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                           'usage': {'output_tokens': 1}}),
        ('message_stop', {'type': 'message_stop'}),
    ]
    return ''.join(f'event: {name}\ndata: {json.dumps(data)}\n\n' for name, data in events)


def create_app(tools, api_key=None, http=None, out=None):
    """The practice door as a Flask app. `http` is the requests module, or a fake of it."""
    app = Flask(__name__)
    tools = list(tools)

    @app.before_request
    def refuse_the_internet():
        host = (request.host or '').rsplit(':', 1)[0].lower()
        target = request.environ.get('REQUEST_URI') or request.environ.get('RAW_URI') or request.path
        if request.method == 'CONNECT':
            record('internet', out, destination=target.lstrip('/'), method='CONNECT')
            return Response('{"error":"not allowed"}', 403, content_type='application/json')
        if host and host not in LOCAL_HOSTS:
            port = 443 if request.scheme == 'https' else 80
            record('internet', out, destination=f'{host}:{port}', method=request.method, path=request.path)
            return Response('{"error":"not allowed"}', 403, content_type='application/json')
        return None

    @app.post('/mcp')
    def mcp():
        try:
            msg = json.loads(request.get_data() or b'{}')
        except ValueError:
            return Response('{"error":"bad json"}', 400, content_type='application/json')
        method = msg.get('method')
        params = msg.get('params') or {}
        tool = params.get('name') if method == 'tools/call' else None
        record('mcp', out, method=method, tool=tool, arguments=params.get('arguments') if tool else None)
        if 'id' not in msg:
            return Response(status=202)
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion') or '2025-06-18',
                      'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'veriphex-practice-door', 'version': '0'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'description': f'{name} (practice: echoes its arguments)',
                                 'inputSchema': {'type': 'object', 'additionalProperties': True}}
                                for name in tools]}
        elif method == 'tools/call':
            if tool in tools:
                text = json.dumps({'practice': True, 'tool': tool, 'arguments': params.get('arguments') or {}})
                result = {'content': [{'type': 'text', 'text': text}], 'isError': False}
            else:
                result = {'content': [{'type': 'text', 'text': f'{tool} is not one of this agent\'s tools.'}],
                          'isError': True}
        elif method == 'ping':
            result = {}
        else:
            return _jsonrpc({'jsonrpc': '2.0', 'id': msg['id'],
                             'error': {'code': -32601, 'message': f'{method} is not supported'}})
        return _jsonrpc({'jsonrpc': '2.0', 'id': msg['id'], 'result': result})

    def _jsonrpc(body):
        resp = Response(json.dumps(body), 200, content_type='application/json')
        resp.headers['Mcp-Session-Id'] = 'practice'
        return resp

    @app.post('/model/anthropic/v1/messages')
    def model():
        raw = request.get_data()
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            body = {}
        record('model', out, model=body.get('model'), stream=bool(body.get('stream')),
               forwarded=bool(api_key))
        if api_key:
            client = http
            if client is None:
                import requests as client
            headers = {k: v for k, v in request.headers.items() if k.lower() in PASS_HEADERS}
            headers['x-api-key'] = api_key
            upstream = client.post(ANTHROPIC_URL, data=raw, headers=headers, stream=True, timeout=600)
            return Response(upstream.iter_content(chunk_size=None), upstream.status_code,
                            content_type=upstream.headers.get('Content-Type', 'application/json'))
        text = 'This is the practice door. Set PRACTICE_ANTHROPIC_API_KEY where it runs for real answers.'
        model_name = body.get('model') or 'practice'
        if body.get('stream'):
            return Response(_canned_stream(model_name, text), 200, content_type='text/event-stream')
        return Response(json.dumps(_canned_message(model_name, text)), 200, content_type='application/json')

    @app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD'])
    @app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD'])
    def anything_else(path):
        record('refused', out, method=request.method, path='/' + path)
        return Response('{"error":"not allowed"}', 403, content_type='application/json')

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description='The Veriphex practice door.')
    parser.add_argument('--tools', default='tools.txt', help='the agent\'s tools.txt')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args(argv)
    tools = read_tools(args.tools)
    key = os.environ.get('PRACTICE_ANTHROPIC_API_KEY') or None
    print(f'Practice door on http://{args.host}:{args.port}  tools: {", ".join(tools) or "none"}  '
          f'model: {"forwarded to Anthropic" if key else "canned answers"}', flush=True)
    create_app(tools, key).run(host=args.host, port=args.port, threaded=True)


if __name__ == '__main__':
    main()
