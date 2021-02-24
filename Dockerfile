FROM  jrottenberg/ffmpeg:4.3-alpine AS ffmpeg


FROM python:3.8
COPY --from=ffmpeg /usr/local /usr/local/
WORKDIR /app

RUN pip install --upgrade pip

COPY . .

# Install package from source code
RUN pip install .

EXPOSE 5000
ENTRYPOINT [ "libretranslate", "--host", "0.0.0.0" ]
