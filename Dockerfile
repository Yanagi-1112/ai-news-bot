FROM python:3.12-slim

WORKDIR /app
RUN useradd --create-home --uid 10001 newsbot
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY prompts ./prompts
COPY sources.yaml ./
RUN mkdir /data && chown -R newsbot:newsbot /app /data
USER newsbot
CMD ["python", "-m", "bot.main"]
