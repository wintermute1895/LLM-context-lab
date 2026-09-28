FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY bin ./bin
COPY config/topic.example.json ./config/topic.example.json

RUN pip install --no-cache-dir .

ENTRYPOINT ["context-lab"]
CMD ["--help"]
