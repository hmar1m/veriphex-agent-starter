# A Veriphex agent with its own small model, run on the CPU by llama.cpp. Pin both images and the
# model by digest or checksum before you submit.
#
# The standard sealed machine (n2d-standard-2) has 2 CPUs, 8 GB of memory and no GPU: choose a
# model of a few GB at most, quantised (for example Q4_K_M), with tool calling.
FROM ghcr.io/ggml-org/llama.cpp:server

ARG MODEL_URL
ARG MODEL_SHA256
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-requests curl \
    && rm -rf /var/lib/apt/lists/*
RUN test -n "$MODEL_URL" && test -n "$MODEL_SHA256" \
    && mkdir -p /models && curl -fL "$MODEL_URL" -o /models/model.gguf \
    && echo "$MODEL_SHA256  /models/model.gguf" | sha256sum -c -

WORKDIR /agent
COPY agent.py start.sh tools.txt ./
RUN useradd --uid 10001 --create-home agent
USER agent
ENTRYPOINT []
CMD ["/agent/start.sh"]
