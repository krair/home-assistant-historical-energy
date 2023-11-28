FROM docker.io/library/python:3.11-slim

COPY ./requirements.txt /requirements.txt

RUN pip3 install -r /app/requirements.txt \

COPY ./app  /app

RUN useradd -M -u 3737 python && \
    chown -R python:python /app && \
    chmod -R 750 /app

USER python

WORKDIR /app

ENTRYPOINT ["/usr/local/bin/python3"]

CMD ["energy_importer.py"]