FROM python:3.14.5-slim-trixie

ENV APKTOOL_VERSION="3.0.2"
ENV BUNDLETOOL_VERSION="1.18.3"
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-25-jdk-headless \
    wget \
    unzip \
    zipalign \
    apksigner \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/apktool && \
    wget -q https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool -O /opt/apktool/apktool && \
    wget -q https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_${APKTOOL_VERSION}.jar -O /opt/apktool/apktool.jar && \
    chmod +x /opt/apktool/apktool /opt/apktool/apktool.jar && \
    ln -s /opt/apktool/apktool /usr/local/bin/apktool && \
    wget -q "https://github.com/google/bundletool/releases/download/${BUNDLETOOL_VERSION}/bundletool-all-${BUNDLETOOL_VERSION}.jar" \
    -O /usr/local/bin/bundletool.jar && chmod a+x /usr/local/bin/bundletool.jar && \
    echo '#!/bin/bash' > /usr/local/bin/bundletool && \
    echo 'java -jar /usr/local/bin/bundletool.jar "$@"' >> /usr/local/bin/bundletool && \
    chmod +x /usr/local/bin/bundletool && \
    wget -q "https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/8.0.2-9289358/aapt2-8.0.2-9289358-linux.jar" -O /tmp/aapt2.jar && \
    unzip -q /tmp/aapt2.jar aapt2 -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/aapt2 && \
    rm /tmp/aapt2.jar

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

ENV PYTHONPATH="/app"
WORKDIR /workdir

ENTRYPOINT ["python3", "-m", "obfuscapk.cli"]
