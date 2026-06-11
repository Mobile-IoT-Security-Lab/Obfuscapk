FROM gradle:9.5.1-jdk21-corretto AS builder

ENV SMALI_VERSION="3.0.9"

WORKDIR /home/gradle/src

RUN git clone -b ${SMALI_VERSION} --depth 1 https://github.com/google/smali.git .

RUN ./gradlew build -x test --no-daemon


FROM python:3.14.5-slim-trixie

ENV APKTOOL_VERSION="3.0.2"
ENV PYTHONUNBUFFERED=1

ENV BAKSMALI_PATH="/opt/smali/baksmali.jar"
ENV SMALI_PATH="/opt/smali/smali.jar"

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-25-jdk-headless \
    wget \
    unzip \
    zipalign \
    apksigner \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/apktool && \
    wget -q https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool -O /opt/apktool/apktool && \
    wget -q https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar -O /opt/apktool/apktool.jar && \
    chmod +x /opt/apktool/apktool /opt/apktool/apktool.jar && \
    ln -s /opt/apktool/apktool /usr/local/bin/apktool

RUN mkdir -p /opt/smali
COPY --from=builder /home/gradle/src/baksmali/build/libs/baksmali-*-fat.jar ${BAKSMALI_PATH}
COPY --from=builder /home/gradle/src/smali/build/libs/smali-*-fat.jar ${SMALI_PATH}
RUN chmod +x ${BAKSMALI_PATH} ${SMALI_PATH}

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

ENV PYTHONPATH="/app"

WORKDIR /workdir

ENTRYPOINT ["python3", "-m", "obfuscapk.cli"]
