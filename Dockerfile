FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml .
COPY quota_sentinel/ quota_sentinel/
RUN pip install --no-cache-dir .

FROM python:3.12-slim
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin/quota-sentinel /usr/local/bin/
USER nobody
ENV PYTHONUNBUFFERED=1
EXPOSE 7878
CMD ["quota-sentinel", "start", "--host", "0.0.0.0"]
