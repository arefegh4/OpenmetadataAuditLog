## stage: check script

FROM 10.1.20.108:8087/python:3.11-slim AS builder

COPY ./omd_audit_to_es.py /tmp/omd_audit_to_es.py

RUN python3 -m py_compile /tmp/omd_audit_to_es.py

##################################################
## stage: build final image

FROM 10.1.20.108:8087/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /tmp/omd_audit_to_es.py /app/omd_audit_to_es.py

WORKDIR /app

ENTRYPOINT ["python3", "omd_audit_to_es.py"]

##################################################