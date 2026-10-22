# Building a Veriphex agent, step by step

You need Docker with `buildx`, the Google Cloud CLI (`gcloud`), cosign (`brew install cosign`),
and Python 3 with `requests`, `cryptography` and `flask`.

## 1. Agree where the package lives

Your package lives in an Artifact Registry Docker repository in your company's Google Cloud, for
example `us-central1-docker.pkg.dev/<project>/agents`.

**Tell your cloud admin which repository holds your package.** The setup script grants the sealed
machines read access only to the repositories named in its `--package-repos`. A package anywhere
else fails when it runs, not when you submit it.

Sign in and let Docker push there:

```
gcloud auth login
gcloud auth configure-docker us-central1-docker.pkg.dev
```

## 2. Write the agent

Copy `template-python/`. Edit `agent.py` for your task. List every tool it uses in `tools.txt`,
one per line, exactly as the form names them: Veriphex refuses a call to any other tool.

The template uses the Claude Agent SDK with `VERIPHEX_MCP_URL` as its only MCP server. It has no
built-in tools, so no WebFetch and no WebSearch, and it sets `skipWebFetchPreflight` so the SDK
makes no check of its own against the internet. Keep it that way: in the sealed space the internet
is closed.

Never put a key, a password or an `.env` file in the package. The agent reaches services only
through Veriphex's tools.

## 3. Practise locally

Start the practice door with your `tools.txt`, and keep its log:

```
python3 practice-door/practice_door.py --tools template-python/tools.txt | tee practice.log
```

It answers tool calls with an echo, and the model with a canned reply. For real model answers, set
`PRACTICE_ANTHROPIC_API_KEY` to your own Anthropic key in the door's terminal only.

In a second terminal, build the agent for your own machine and run it against the door:

```
cd template-python
docker buildx build --load -t my-agent:practice .
mkdir -p work && echo '{"task": "Check invoice 1001", "person": {"name": "Sam"}, "job_no": 1, "job_label": "practice"}' > work/task.json
docker run --rm -v "$PWD/work:/veriphex/work" \
  -e VERIPHEX_TASK_FILE=/veriphex/work/task.json -e VERIPHEX_RESULT_FILE=/veriphex/work/result.txt \
  -e VERIPHEX_MCP_URL=http://host.docker.internal:8080/mcp \
  -e ANTHROPIC_BASE_URL=http://host.docker.internal:8080/model/anthropic \
  -e ANTHROPIC_API_KEY=placeholder-not-a-key -e VERIPHEX_MODEL=claude-sonnet-5-5 \
  -e HTTPS_PROXY=http://host.docker.internal:8080 -e HTTP_PROXY=http://host.docker.internal:8080 \
  -e NO_PROXY=host.docker.internal \
  my-agent:practice
cat work/result.txt
```

On Linux, add `--network host` and use `127.0.0.1` in place of `host.docker.internal`.

The proxy settings send any direct internet attempt to the door, which refuses and records it.
Then check the run:

```
veriphex_check/veriphex-check --practice-log practice.log --tools template-python/tools.txt
```

It names every call to a tool `tools.txt` does not declare, and every direct internet attempt.

## 4. Build and push

```
./template-python/build.sh --repo us-central1-docker.pkg.dev/<project>/agents --name invoice-checker
```

It runs `docker buildx build --platform linux/amd64,linux/arm64 … --push`, and prints the package
link by digest:

```
us-central1-docker.pkg.dev/<project>/agents/invoice-checker@sha256:<64 characters>
```

Veriphex accepts only a link by digest, because a digest names exactly one set of bytes. The
sealed machines run linux/amd64; arm64 is for your own practice runs.

## 5. Make your signing key, once

```
cosign generate-key-pair
```

Choose a password. Keep `cosign.key` private, and never put it in a package. On your Veriphex
account page, **Build agents** → paste the contents of `cosign.pub` → **Save**.

## 6. Sign the package

```
cosign sign --key cosign.key --new-bundle-format=false <link>
```

`--new-bundle-format=false` keeps cosign's classic format: a `sha256-<digest>.sig` tag beside the
package, holding a simple-signing payload and its signature. That is what Veriphex reads, at
submission and at every run. Cosign 3 changed its default to a newer bundle format, which Veriphex
does not read, so the flag is required.

## 7. Check it

```
veriphex_check/veriphex-check <link> --key cosign.pub --tools template-python/tools.txt \
  --password "$(gcloud auth print-access-token)"
```

It tells you, in plain sentences:
- whether the package is signed with your key;
- anything in it that looks like a secret;
- whether it has a linux/amd64 version;
- files over 200 MB, which may be an AI model you must declare on the form.

## 8. Submit

Run `gcloud auth print-access-token` and copy what it prints. It is your read-only password for
the package: it lasts one hour, Veriphex uses it once to read the package and does not keep it,
and no key file is made.

On your Veriphex account page: **Build agents** → **Add an agent**. Fill in the name, the tools
(the same as `tools.txt`), where it runs (*Your Google Cloud (sealed)*), the kind of AI model, and
any built-in model. Paste the link and the password → **Add to bank**.

Veriphex checks the fingerprint, the linux/amd64 version and your signature, and keeps no copy of
the package. If you later delete the package from the registry, its runs fail and say so.
