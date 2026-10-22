# A Veriphex agent package. Pin the base image by digest before you submit:
#   FROM python:3.12-slim-bookworm@sha256:<digest>
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py tools.txt ./

# Never copy keys, .env files or credentials into the package: veriphex-check looks for them,
# and the agent reaches services only through Veriphex's tools.
RUN useradd --uid 10001 --create-home agent
USER agent
ENV HOME=/home/agent
CMD ["python", "/agent/agent.py"]
