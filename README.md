# Veriphex agent starter kit (version 0)

Everything a builder needs to make an agent that runs in Veriphex's sealed space: the company's
own Google Cloud, on a Confidential VM, reaching its tools and its AI model only through Veriphex.

| Folder | What it is |
|---|---|
| `template-python/` | An agent on the Claude Agent SDK. Start here. |
| `template-builtin-model/` | The same, with its own small model run on the CPU by llama.cpp. Its use is not counted. |
| `practice-door/` | A local stand-in for Veriphex's door, for practice runs. It prints every request. |
| `veriphex_check/` | `veriphex-check`: what Veriphex will think of your package, before you submit it. |
| `examples/tries-internet/` | An agent that tries to reach the internet directly, for the forgery check. |

`GUIDE.md` takes you from an empty folder to a submitted agent, step by step.

## The contract

Inside the sealed space your package is started with:

| Variable | Meaning |
|---|---|
| `VERIPHEX_TASK_FILE` | JSON with `task`, `person`, `job_no`, `job_label` |
| `VERIPHEX_RESULT_FILE` | where the agent writes its answer before it exits |
| `VERIPHEX_MCP_URL` | the agent's only MCP server: the tools it declared |
| `ANTHROPIC_BASE_URL` | Veriphex's model door (absent when the agent needs no outside model) |
| `ANTHROPIC_API_KEY` | a placeholder; Veriphex adds the real key on its side |
| `VERIPHEX_MODEL` | the model the organisation chose |

Anything else the agent tries to reach is refused and reported. The agent has 25 minutes.
