<p align="center">
  <img src="docs/logo/logo.png" alt="Obfuscapk logo" width="420">
</p>

# Obfuscapk

> A black-box obfuscation tool for Android applications.

[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Android](https://img.shields.io/badge/Android-APK%20%7C%20AAB-brightgreen.svg?logo=android&logoColor=white)](https://developer.android.com/)

Obfuscapk is a modular Python tool for obfuscating Android applications without requiring their source code. It works in a black-box fashion: it decompiles the input application with [`apktool`](https://ibotpeaches.github.io/Apktool/), applies a configurable sequence of obfuscation plugins to the decompiled `smali` code, resources and manifest, and rebuilds a new application package.

This repository is the official Mobile-IoT-Security Lab fork and the current reference point for research, maintenance and community contributions around Obfuscapk.

## Responsible use

Obfuscapk is a research and education tool for studying Android obfuscation, program transformation, reverse engineering, malware analysis robustness and application protection. Use it only on applications you own, are authorized to analyze, or are allowed to transform for research purposes.

Do not use Obfuscapk to hide malware, bypass security products, evade app-store review, or interfere with systems you do not own or administer. Issues and pull requests aimed at improving security research, reproducibility, compatibility and legitimate application protection are welcome.

## Features

- Black-box Android app obfuscation: no access to source code is required.
- Modular plugin architecture based on independent obfuscators.
- Transformations for code, identifiers, strings, resources, native libraries and packaging metadata.
- Configurable obfuscator order through command line options.
- Support for APK files and experimental support for Android App Bundles (`.aab`).
- Docker and Docker Compose environment for reproducible execution.
- Custom signing support for APK and AAB files through user-provided keystores.
- Method renaming mappings for inspecting the changes applied to an application.
- Automatic multidex repartitioning when selected obfuscators add methods or fields.

## Supported inputs

| Format | Status | Notes |
| --- | --- | --- |
| `.apk` | Supported | Main target format. |
| `.aab` | Experimental | Processes the base module with apktool, aapt2, smali and baksmali. Requires `jarsigner` for signing. |

A successful obfuscation process means that Obfuscapk completed the transformation and produced an output package. It does not guarantee that the transformed application behaves exactly like the original one. Some applications use anti-tampering, integrity checks, dynamic loading, native code, resource assumptions or framework-specific patterns that can make repackaging and obfuscation fail.

## Publication

More details about Obfuscapk can be found in the paper:

> Simone Aonzo, Gabriel Claudiu Georgiu, Luca Verderame, Alessio Merlo, "Obfuscapk: An open-source black-box obfuscation tool for Android apps", SoftwareX, Volume 11, 2020, 100403.

Please cite Obfuscapk as follows:

```bibtex
@article{aonzo2020obfuscapk,
  title = {Obfuscapk: An open-source black-box obfuscation tool for Android apps},
  journal = {SoftwareX},
  volume = {11},
  pages = {100403},
  year = {2020},
  issn = {2352-7110},
  doi = {https://doi.org/10.1016/j.softx.2020.100403},
  url = {https://www.sciencedirect.com/science/article/pii/S2352711019302791},
  author = {Simone Aonzo and Gabriel Claudiu Georgiu and Luca Verderame and Alessio Merlo},
  keywords = {Android, Obfuscation, Program analysis}
}
```

## Architecture

<p align="center">
  <img src="docs/architecture/architecture.png" alt="Obfuscapk architecture" width="720">
</p>

Obfuscapk is designed around a plugin system. Each obfuscation technique is implemented as a plugin that inherits from the base obfuscator class and implements the `obfuscate` method.

Plugins are discovered from `.obfuscator` metadata files with Python's standard library. Yapsy is no longer required.

During execution, Obfuscapk creates an obfuscation object that stores the paths, intermediate state, configuration and metadata needed by the active plugins. The object is passed to each selected obfuscator in sequence. The list and order of active obfuscators are specified through command line options.

When selected obfuscators add methods or fields, the smali files are repartitioned before rebuilding. The partitioning counts unique method and field declarations and references, and constant strings, with a target of 10,000 entries per category in each DEX partition. This reduces DEX limit failures but does not guarantee that every application can be rebuilt.

To add a new obfuscator:

1. Create a new directory under `src/obfuscapk/obfuscators/`.
2. Implement the obfuscator logic by following the structure of an existing simple plugin such as `Nop`.
3. Add the corresponding `.obfuscator` plugin metadata file.
4. Run `python3 -m obfuscapk.cli --help` to verify that the new plugin is discovered.

## Installation

There are two recommended installation paths:

- Docker Compose, recommended for reproducible experiments.
- Source installation, useful for development and for adding new obfuscators.

### Docker Compose

Docker Compose builds a local image from this repository and mounts two host directories:

- `./apks` as `/workdir`, for input applications.
- `./output` as `/output`, for obfuscated applications.

```bash
git clone https://github.com/Mobile-IoT-Security-Lab/Obfuscapk.git
cd Obfuscapk
mkdir -p apks output

docker compose build
docker compose run --rm obfuscapk --help
```

Place the input APK or AAB inside `./apks`, then run Obfuscapk through Docker Compose:

```bash
docker compose run --rm obfuscapk \
  -o DebugRemoval \
  -o ConstStringEncryption \
  -o Rebuild \
  -o NewAlignment \
  -o NewSignature \
  --cleanup \
  --output-dir /output \
  original.apk
```

The obfuscated output will be written to `./output`.

If file ownership matters on Linux or WSL, you can pass the current UID and GID explicitly:

```bash
UID=$(id -u) GID=$(id -g) docker compose run --rm obfuscapk --help
```

### Local Docker image

You can also build and run the image directly with Docker:

```bash
git clone https://github.com/Mobile-IoT-Security-Lab/Obfuscapk.git
cd Obfuscapk
mkdir -p apks output

docker build -t obfuscapk .
docker run --rm -it -v "${PWD}/apks":/workdir -v "${PWD}/output":/output obfuscapk --help
```

Example:

```bash
docker run --rm -it \
  -v "${PWD}/apks":/workdir \
  -v "${PWD}/output":/output \
  obfuscapk \
  -o Nop \
  -o Rebuild \
  -o NewAlignment \
  -o NewSignature \
  --cleanup \
  original.apk
```

The Docker image includes Python 3.14.5, OpenJDK 25, apktool 3.0.2 and smali/baksmali 3.0.9. The root `Dockerfile` is used for both Docker and Docker Compose.

A legacy Docker Hub image may still exist under the original namespace. For this maintained fork, prefer building the Docker image from the current repository unless a new official image is explicitly published by the maintainers.

Apktool uses a maximum Java heap of 4 GiB by default in the Docker image and the
bundled `bin/apktool` launcher. Memory is allocated as needed. Rebuild existing
Docker images to apply this setting; the container must have enough memory for
the Java heap and the other running processes.

### From source

Use Python 3.10 or later. The test workflows cover Python 3.10 through 3.14 on Linux, macOS and Windows.

Install the external tools required by Obfuscapk and make sure they are available from the command line:

- [`apktool`](https://ibotpeaches.github.io/Apktool/)
- [`apksigner`](https://developer.android.com/studio/command-line/apksigner)
- [`zipalign`](https://developer.android.com/studio/command-line/zipalign)
- Java runtime compatible with the selected Android tools
- for AAB support, `aapt2`, the smali and baksmali JAR files, and a JDK providing `jarsigner`

`zipalign`, `apksigner` and `aapt2` are included in the Android SDK Build Tools. The Docker image provides the dependencies for both APK and AAB processing.

The location of the external tools can be customized with environment variables:

```bash
export APKTOOL_PATH=/custom/path/apktool
export APKSIGNER_PATH=/custom/path/apksigner
export ZIPALIGN_PATH=/custom/path/zipalign
```

Install the Python dependencies:

```bash
git clone https://github.com/Mobile-IoT-Security-Lab/Obfuscapk.git
cd Obfuscapk

python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r src/requirements.txt

cd src
python3 -m obfuscapk.cli --help
```

When running from source, execute Obfuscapk from the `src/` directory or add `Obfuscapk/src` to `PYTHONPATH`.

## Android App Bundle support

Obfuscapk includes experimental support for Android App Bundles (`.aab`) through an internal pipeline. The external `BundleDecompiler.jar` and the `BUNDLE_DECOMPILER_PATH` setting are no longer used.

The pipeline extracts the bundle, disassembles the base module's DEX files with baksmali, and uses aapt2 and apktool to convert the manifest and resources into a form that the plugins can modify. During rebuilding, smali assembles the modified code and the manifest and resources are converted back to protobuf format. Other bundle modules are retained, but their code is not processed by this pipeline.

For a source installation, configure the additional tools:

```bash
export BAKSMALI_PATH=/custom/path/baksmali.jar
export SMALI_PATH=/custom/path/smali.jar
export AAPT2_PATH=/custom/path/aapt2
```

By default, the JAR files are expected at `/opt/smali/baksmali.jar` and `/opt/smali/smali.jar`, and `aapt2` is resolved from `PATH`. Java and `jarsigner` must also be available from the command line. The current pipeline assembles and disassembles DEX files with API level 30.

AAB files are signed with `jarsigner`; APK files are signed with `apksigner`. `NewAlignment` is skipped for AAB files. Both formats support the bundled test keystore and custom keystores.

Example:

```bash
docker compose run --rm obfuscapk \
  -o DebugRemoval \
  -o ConstStringEncryption \
  -o Rebuild \
  -o NewSignature \
  --cleanup \
  --output-dir /output \
  original.aab
```

AAB support should be considered experimental. Validate the output package carefully, especially when working with modern Android projects, split configurations, dynamic features or non-standard build pipelines.

## Usage

The general command format is:

```bash
obfuscapk -o OBFUSCATOR [-o OBFUSCATOR ...] [options] APK_OR_AAB_FILE
```

Depending on the installation method, replace `obfuscapk` with one of the following:

```bash
# Docker Compose
docker compose run --rm obfuscapk [options] APK_OR_AAB_FILE

# Docker
docker run --rm -it -v "${PWD}/apks":/workdir -v "${PWD}/output":/output obfuscapk [options] APK_OR_AAB_FILE

# From source, inside Obfuscapk/src
python3 -m obfuscapk.cli [options] APK_OR_AAB_FILE
```

### Common examples

Minimal repackaging test:

```bash
obfuscapk \
  -o Rebuild \
  -o NewAlignment \
  -o NewSignature \
  original.apk
```

Basic obfuscation:

```bash
obfuscapk \
  -o DebugRemoval \
  -o Nop \
  -o ConstStringEncryption \
  -o Rebuild \
  -o NewAlignment \
  -o NewSignature \
  original.apk
```

More aggressive obfuscation:

```bash
obfuscapk \
  -o DebugRemoval \
  -o LibEncryption \
  -o CallIndirection \
  -o MethodRename \
  -o AssetEncryption \
  -o MethodOverload \
  -o ConstStringEncryption \
  -o ResStringEncryption \
  -o ArithmeticBranch \
  -o FieldRename \
  -o Nop \
  -o Goto \
  -o ClassRename \
  -o Reflection \
  -o AdvancedReflection \
  -o Reorder \
  -o RandomManifest \
  -o Rebuild \
  -o NewAlignment \
  -o NewSignature \
  --cleanup \
  original.apk
```

Always keep `Rebuild`, `NewAlignment` and `NewSignature` after the transformation obfuscators. They are not obfuscation techniques by themselves, but they are needed to build, align and sign the output APK. For AAB files, use `Rebuild` and `NewSignature`; alignment is skipped.

### Options

| Option | Description |
| --- | --- |
| `-o`, `--obfuscator OBFUSCATOR` | Select an obfuscator. Can be specified multiple times. Order matters. |
| `-w`, `--working-dir DIR` | Directory for intermediate files. Created automatically if missing. |
| `-d`, `--destination OUT_APK_OR_AAB` | Output file path before the final move to `--output-dir`. Existing files can be overwritten. |
| `-i`, `--ignore-libs` | Skip known third-party libraries during obfuscation. |
| `-p`, `--show-progress` | Show progress bars during obfuscation. Enabled automatically when standard output is a terminal. |
| `--ignore-packages-file FILE` | File containing package names to ignore, one package per line. |
| `--use-aapt2` | Accepted for compatibility. Rebuilding uses apktool's default resource compiler; this option is not passed to apktool. |
| `--cleanup` | Remove the intermediate working directory after a successful run. |
| `--output-dir DIR` | Move the final output package to the selected directory. Defaults to `/output` for all installation methods. |
| `--keystore-file FILE` | Custom keystore for signing the output APK or AAB. |
| `--keystore-password PASSWORD` | Password for the custom keystore. |
| `--key-alias ALIAS` | Alias of the key inside the custom keystore. |
| `--key-password PASSWORD` | Password of the selected key, if different from the keystore password. |
| `-k`, `--virus-total-key VT_API_KEY` | API key used only by the `VirusTotal` plugin. |

For source installations, set `--output-dir` to a writable directory. The output package is moved there after the selected plugins finish, including when `--destination` is provided. `--cleanup` removes the intermediate working directory after a successful run.

When no custom keystore is provided, Obfuscapk uses the test keystore bundled with the project. Use a custom keystore when the signature matters for your experiment or test workflow.

To ignore custom packages, create a file such as `ignore-packages.txt`:

```text
com.example.do_not_obfuscate
com.vendor.ignore
```

Then run:

```bash
obfuscapk --ignore-packages-file ignore-packages.txt -o Rebuild -o NewAlignment -o NewSignature original.apk
```

## Obfuscators

The obfuscators bundled with Obfuscapk are grouped into categories:

- `Trivial`: build, alignment and signing operations needed by the pipeline.
- `Rename`: identifier renaming for classes, methods and fields.
- `Encryption`: encryption of strings, resources, assets or native libraries.
- `Code`: transformations that modify the decompiled smali code.
- `Resources`: transformations on resources and manifest files.
- `Other`: auxiliary plugins.

| Obfuscator | Category | Description |
| --- | --- | --- |
| `AdvancedReflection` | Code | Uses reflection to invoke selected Android framework APIs. |
| `ArithmeticBranch` | Code | Inserts arithmetic junk code and opaque branches that are not expected to be taken. |
| `AssetEncryption` | Encryption | Encrypts asset files and adds runtime support for their use. |
| `CallIndirection` | Code | Replaces direct method invocations with wrapper methods. |
| `ClassRename` | Rename | Changes package names and renames classes, including manifest references. |
| `ConstStringEncryption` | Encryption | Encrypts constant strings in code. |
| `DebugRemoval` | Code | Removes debug information from smali code. |
| `FieldRename` | Rename | Renames fields and updates inherited references while preserving selected runtime and reflection names. |
| `Goto` | Code | Adds `goto` instructions to modify the control-flow graph. |
| `LibEncryption` | Encryption | Encrypts native libraries when compatible with the loading pattern. |
| `MethodOverload` | Code | Adds overloaded methods with additional random arguments and junk instructions. |
| `MethodRename` | Rename | Renames suitable methods consistently across class hierarchies and exports a JSON mapping. |
| `NewAlignment` | Trivial | Aligns the output package with `zipalign`. |
| `NewSignature` | Trivial | Signs the output package. |
| `Nop` | Code | Inserts random `nop` instructions. |
| `RandomManifest` | Resources | Randomly reorders manifest entries while keeping activity aliases after their target activities. |
| `Rebuild` | Trivial | Rebuilds the application package. |
| `Reflection` | Code | Redirects suitable app method invocations through Java reflection. |
| `Reorder` | Code | Reorders basic blocks and adjusts branches using `goto` instructions. |
| `ResStringEncryption` | Encryption | Encrypts selected string and string-array resources referenced from supported code patterns, including localized values. |
| `VirusTotal` | Other | Submits selected artifacts to VirusTotal. Requires an API key. Do not use it with confidential applications unless you are authorized to upload them. |

Not every plugin is a pure obfuscation technique. `Rebuild`, `NewAlignment`, `NewSignature` and `VirusTotal` are implemented as plugins to keep the pipeline modular.

## Troubleshooting

### Start with a minimal rebuild

Before combining several transformations, verify that the application can be repackaged:

```bash
obfuscapk -o Rebuild -o NewAlignment -o NewSignature original.apk
```

If this fails, the issue is likely related to decompilation, rebuilding, signing, anti-tampering logic, tool versions or application-specific packaging assumptions.

### Add obfuscators incrementally

If minimal repackaging works but a larger configuration fails, add obfuscators one by one until the problematic transformation is isolated. The order of obfuscators matters.

### Enable logs

By default, Obfuscapk prints only error messages. To enable debug logging:

```bash
LOG_LEVEL=DEBUG obfuscapk -o Rebuild -o NewAlignment -o NewSignature original.apk
```

With Docker Compose:

```bash
LOG_LEVEL=DEBUG docker compose run --rm obfuscapk -o Rebuild -o NewAlignment -o NewSignature original.apk
```

### Common causes of failure

- Old `apktool` versions.
- Missing `apksigner` or `zipalign`.
- Missing or incompatible Java runtime.
- AAB processing without aapt2, smali, baksmali or `jarsigner`.
- AAB code that requires a newer API level than the pipeline's current smali setting.
- An unwritable output directory, especially the default `/output` in source installations.
- Applications protected by anti-repackaging or integrity checks.
- Transformations applied to third-party libraries that should be ignored.
- Obfuscator ordering issues.

For more details, see [`docs/FAQ.md`](docs/FAQ.md) and [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Contributing

Contributions are welcome. Useful contributions include:

- Bug fixes for APK or AAB processing.
- Compatibility improvements for recent Android build tools.
- New obfuscation plugins.
- De-obfuscation and detection benchmarks.
- Documentation updates.
- Reproducible test cases.

Before opening an issue, please include:

- Operating system and installation method.
- Obfuscapk commit hash.
- Python version.
- `apktool`, `apksigner`, `zipalign` and Java versions.
- Full command line used.
- List and order of obfuscators.
- Whether minimal repackaging works.
- Debug logs when possible.

Open issues and pull requests in this repository:

- Issues: https://github.com/Mobile-IoT-Security-Lab/Obfuscapk/issues
- Pull requests: https://github.com/Mobile-IoT-Security-Lab/Obfuscapk/pulls

## License

Obfuscapk is released under the [MIT License](LICENSE).

## Credits

Obfuscapk was originally developed for research purposes at the Computer Security Lab, hosted at DIBRIS, University of Genoa.

Original authors:

- Simone Aonzo
- Gabriel Claudiu Georgiu
- Luca Verderame
- Alessio Merlo

Current maintenance and research development are coordinated through the Mobile-IoT-Security Lab fork.
