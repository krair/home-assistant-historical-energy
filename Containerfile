FROM docker.io/library/python:3.11-alpine

COPY ./app /app

RUN apk add --no-cache --virtual build-dependencies python3 \
    && apk add --virtual build-runtime \
    build-base python3-dev pkgconfig \
    && ln -s /usr/include/locale.h /usr/include/xlocale.h \
    && pip3 install --upgrade pip setuptools \
    && pip3 install -r /app/requirements.txt \
    && apk del build-runtime python3-dev pkgconfig\
    && rm -rf /var/cache/apk/*

RUN adduser -D -H -u 3737 python python && \
    chown -R python:python /app && \
    chmod -R 750 /app

USER python

WORKDIR /app

ENTRYPOINT ["/usr/bin/python3"]

CMD ["energy_importer.py"]