# Example: an agent that tries the internet

Used for the forgery check. Build, sign and submit it like any agent:

```
docker buildx build --platform linux/amd64,linux/arm64 \
  -t us-central1-docker.pkg.dev/<project>/agents/tries-internet:v1 --push \
  --metadata-file meta.json .
cosign sign --key cosign.key --new-bundle-format=false \
  us-central1-docker.pkg.dev/<project>/agents/tries-internet@<digest from meta.json>
```

Run it once. Its answer must say the attempt failed, and the job must show an egress refusal for
`example.com:443`. Locally, run it against the practice door with
`HTTPS_PROXY=http://127.0.0.1:8080`; `veriphex-check --practice-log` then reports the attempt.
