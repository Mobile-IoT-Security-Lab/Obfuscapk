FROM python:3.9-slim-bookworm

ENV APKTOOL_VERSION="2.9.3"
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
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
    wget -q "https://raw.githubusercontent.com/TamilanPeriyasamy/BundleDecompiler/master/build/libs/BundleDecompiler-0.0.2.jar" \
    -O /usr/local/bin/BundleDecompiler.jar && chmod a+x /usr/local/bin/BundleDecompiler.jar

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

ENV PYTHONPATH="/app"
WORKDIR /workdir

ENTRYPOINT ["python3", "-m", "obfuscapk.cli"]
