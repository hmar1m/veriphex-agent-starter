"""A Veriphex agent built on the Claude Agent SDK.

Inside the sealed space Veriphex hands the agent its job through the environment:
- VERIPHEX_TASK_FILE: JSON with "task", "person", "job_no" and "job_label";
- VERIPHEX_MCP_URL: the only MCP server it may use, Veriphex's door to the tools in tools.txt;
- VERIPHEX_MODEL: the model the organisation chose; ANTHROPIC_BASE_URL already points at
  Veriphex's model door, and ANTHROPIC_API_KEY is a placeholder, never a real key.
The agent writes its answer to VERIPHEX_RESULT_FILE and exits.

It has no built-in tools at all, so it cannot read the web (no WebFetch, no WebSearch) or run
commands; everything it does goes through the declared tools, which Veriphex governs and records.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

HERE = Path(__file__).resolve().parent
SERVER = 'veriphex'

INSTRUCTIONS = (
    'You are an agent working for one person at their company. Do the task using only the tools '
    'you have. When you are done, reply with the answer for the person, in plain sentences.'
)


def declared_tools():
    names = []
    for line in (HERE / 'tools.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            names.append(line.split()[0])
    return names


def options():
    return ClaudeAgentOptions(
        model=os.environ.get('VERIPHEX_MODEL') or None,
        system_prompt=INSTRUCTIONS,
        mcp_servers={SERVER: {'type': 'http', 'url': os.environ['VERIPHEX_MCP_URL']}},
        strict_mcp_config=True,
        tools=[],                                   # no built-in tools: no files, shell or web
        disallowed_tools=['WebFetch', 'WebSearch'],
        allowed_tools=[f'mcp__{SERVER}__{name}' for name in declared_tools()],
        permission_mode='dontAsk',                  # anything not declared is denied, never asked
        setting_sources=[],                         # read no settings files from the image
        settings=json.dumps({'skipWebFetchPreflight': True}),
        max_turns=40,
    )


async def run():
    job = json.loads(Path(os.environ['VERIPHEX_TASK_FILE']).read_text(encoding='utf-8'))
    person = job.get('person') or {}
    prompt = f"Task from {person.get('name') or 'the person'} (job {job.get('job_no')}):\n\n{job['task']}"
    answer, failed = '', False
    async for message in query(prompt=prompt, options=options()):
        if isinstance(message, ResultMessage):
            answer = message.result or ''
            failed = message.is_error
    Path(os.environ['VERIPHEX_RESULT_FILE']).write_text(answer, encoding='utf-8')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(run()))
