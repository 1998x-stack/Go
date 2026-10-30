# Prebuild this trusted QA runtime, then isolate actual test execution with --network none.
FROM python:3.11-slim
COPY quality_gate/requirements-ci.txt /requirements-ci.txt
RUN pip install --no-cache-dir -r /requirements-ci.txt
WORKDIR /work
