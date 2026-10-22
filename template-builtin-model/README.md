# Template: an agent with its own model

The same contract as `template-python`, but the AI model runs inside the package, on the CPU,
with llama.cpp. Nothing leaves the sealed space for the model, so **its use is not counted** by
Veriphex. Declare it on the form (name and rough size) so the person and the admin know it is
there; `veriphex-check` reminds you, because the model file is large.

The standard sealed machine has 2 CPUs, 8 GB of memory and no GPU. Use a small quantised model
with tool calling, and expect answers to take longer than with an outside model.

```
./build.sh --repo us-central1-docker.pkg.dev/<project>/agents \
  --model-url https://…/model.gguf --model-sha256 <hex>
```

Then sign and check it as `GUIDE.md` says.
