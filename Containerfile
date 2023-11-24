FROM docker.io/library/python:3.11

COPY ./app /app

COPY ./config /app/config

RUN useradd -M -u 3737 python; \
    chown -R python:python /app; \
    chmod -R 750 /app; \
    chmod 640 /app/config/*

USER python

WORKDIR /app

RUN pip install -U pip;\
	pip install -r requirements.txt

ENTRYPOINT ["/usr/bin/python3"]

CMD ["energy_importer.py"]