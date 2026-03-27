# Obfuscapk Dockerized Environment

This setup provide a consistent execution environment for Obfuscapk, including all necessary dependencies (Python 3.9, OpenJDK 17, Apktool 2.9.3, and Android Build Tools 33.0.3+).

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1.  **Prepare APKs**: Place the source files in the `./apks` directory.
2.  **Build**:
    ```bash
    docker compose build
    ```
3.  **Run**:
    ```bash
    docker compose run --rm obfuscapk -o <plugin_name_1> -o <plugin_name_2> ... -o <plugin_name_n> -o Rebuild -o NewAlignment -o NewSignature --cleanup <app_name>.apk
    ```

## Implementation Details

- **Output**: Obfuscated APKs are saved in the `./output` host directory by default.
- **Cleanup**: Specify `--cleanup` to remove the intermediate working directory after a successful build.
- **Permissions**: The container automatically maps the host `UID`/`GID` to ensure correct file ownership on Linux/WSL.
- **I/O**: Real-time progress monitoring is enabled by default (INFO level).

---
**Troubleshooting**: To list all available obfuscation plugins and options, run:
`docker compose run --rm obfuscapk --help`
