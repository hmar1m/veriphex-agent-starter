FROM python:3.12-slim-bookworm
WORKDIR /agent
COPY agent.py tools.txt ./
RUN useradd --uid 10001 agent
USER agent
CMD ["python", "/agent/agent.py"]
