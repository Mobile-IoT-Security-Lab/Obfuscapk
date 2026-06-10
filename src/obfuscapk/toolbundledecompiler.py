#!/usr/bin/env python3

import logging
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from typing import List

from obfuscapk.tool import Apktool


class BundleDecompiler(object):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )

        self.bundletool = shutil.which("bundletool") or "bundletool"
        self.aapt2 = shutil.which("aapt2") or "aapt2"
        self.apktool = Apktool()

    def decode(
        self, aab_path: str, output_dir_path: str = None, force: bool = False
    ) -> str:
        # Check if the aab file to decode is a valid file.
        if not os.path.isfile(aab_path):
            self.logger.error('Unable to find file "{0}"'.format(aab_path))
            raise FileNotFoundError('Unable to find file "{0}"'.format(aab_path))

        # If no output directory is specified, use a new directory in the same
        # directory as the aab file to decode.
        if not output_dir_path:
            output_dir_path = os.path.join(
                os.path.dirname(aab_path),
                os.path.splitext(os.path.basename(aab_path))[0],
            )
            self.logger.debug(
                "No output directory provided, the result will be saved in the "
                "same directory as the input file, in a directory with the same "
                'name as the input file: "{0}"'.format(output_dir_path)
            )

        # If an output directory is provided, make sure that the path to that
        # directory exists (the final directory will be created by aabtool).
        elif not os.path.isdir(os.path.dirname(output_dir_path)):
            self.logger.error(
                'Unable to find output directory "{0}", aabtool won\'t be able to '
                'create the directory "{1}"'.format(
                    os.path.dirname(output_dir_path), output_dir_path
                )
            )
            raise NotADirectoryError(
                'Unable to find output directory "{0}", aabtool won\'t be able to '
                'create the directory "{1}"'.format(
                    os.path.dirname(output_dir_path), output_dir_path
                )
            )

        # Inform the user if an existing output directory is provided without the
        # "force" flag.
        if os.path.isdir(output_dir_path) and not force:
            self.logger.error(
                'Output directory "{0}" already exists, use the "force" flag '
                "to overwrite".format(output_dir_path)
            )
            raise FileExistsError(
                'Output directory "{0}" already exists, use the "force" flag '
                "to overwrite".format(output_dir_path)
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            apks_path = os.path.join(temp_dir, "app.apks")

            build_apks_cmd = [
                self.bundletool,
                "build-apks",
                f"--bundle={aab_path}",
                f"--output={apks_path}",
                "--mode=universal",
            ]
            self.logger.info(
                f"Generating universal APK from AAB: {' '.join(build_apks_cmd)}"
            )
            subprocess.check_output(build_apks_cmd, stderr=subprocess.STDOUT)

            universal_apk_path = os.path.join(temp_dir, "universal.apk")
            with zipfile.ZipFile(apks_path, "r") as zip_ref:
                zip_ref.extract("universal.apk", temp_dir)

            self.logger.info("Decoding universal APK using Apktool wrapper...")
            return self.apktool.decode(universal_apk_path, output_dir_path, force)

    def build(self, source_dir_path: str, output_aab_path: str = None) -> str:
        # Check if the input directory exists.
        if not os.path.isdir(source_dir_path):
            self.logger.error(
                'Unable to find source directory "{0}"'.format(source_dir_path)
            )
            raise NotADirectoryError(
                'Unable to find source directory "{0}"'.format(source_dir_path)
            )

        # If no output aab path is specified, the new aab will be saved in the
        # default path: <source_dir_path>/dist/<source_dir_name>.aab
        if not output_aab_path:
            output_aab_path = os.path.join(
                source_dir_path,
                "output",
                "{0}.aab".format(os.path.basename(source_dir_path)),
            )
            self.logger.debug(
                "No output aab path provided, the new aab will be saved in the "
                'default path: "{0}"'.format(output_aab_path)
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_apk_path = os.path.join(temp_dir, "temp.apk")
            proto_apk_path = os.path.join(temp_dir, "proto.apk")
            base_dir = os.path.join(temp_dir, "base")
            base_zip_path = os.path.join(temp_dir, "base.zip")

            self.logger.info("Building binary APK using Apktool wrapper...")
            self.apktool.build(source_dir_path, temp_apk_path)

            aapt2_cmd = [
                self.aapt2,
                "convert",
                "--output-format",
                "proto",
                "-o",
                proto_apk_path,
                temp_apk_path,
            ]
            self.logger.info("Converting to Protobuf format via AAPT2...")
            subprocess.check_output(aapt2_cmd, stderr=subprocess.STDOUT)

            os.makedirs(base_dir)
            with zipfile.ZipFile(proto_apk_path, "r") as zip_ref:
                zip_ref.extractall(base_dir)

            meta_inf_dir = os.path.join(base_dir, "META-INF")
            if os.path.exists(meta_inf_dir):
                shutil.rmtree(meta_inf_dir)

            manifest_dir = os.path.join(base_dir, "manifest")
            os.makedirs(manifest_dir, exist_ok=True)
            if os.path.exists(os.path.join(base_dir, "AndroidManifest.xml")):
                shutil.move(
                    os.path.join(base_dir, "AndroidManifest.xml"),
                    os.path.join(manifest_dir, "AndroidManifest.xml"),
                )

            dex_dir = os.path.join(base_dir, "dex")
            os.makedirs(dex_dir, exist_ok=True)
            for file_name in os.listdir(base_dir):
                if file_name.endswith(".dex"):
                    shutil.move(
                        os.path.join(base_dir, file_name),
                        os.path.join(dex_dir, file_name),
                    )

            root_dir = os.path.join(base_dir, "root")
            os.makedirs(root_dir, exist_ok=True)
            for file_name in os.listdir(base_dir):
                file_path = os.path.join(base_dir, file_name)
                if os.path.isfile(file_path) and file_name not in ["resources.pb"]:
                    shutil.move(file_path, os.path.join(root_dir, file_name))
                elif os.path.isdir(file_path) and file_name not in [
                    "manifest",
                    "dex",
                    "res",
                    "assets",
                    "lib",
                    "root",
                ]:
                    shutil.move(file_path, os.path.join(root_dir, file_name))

            with zipfile.ZipFile(base_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(base_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, base_dir)
                        zipf.write(file_path, arcname)

            bundletool_cmd = [
                self.bundletool,
                "build-bundle",
                f"--modules={base_zip_path}",
                f"--output={output_aab_path}",
            ]
            self.logger.info("Building final AAB via bundletool...")
            output = subprocess.check_output(bundletool_cmd, stderr=subprocess.STDOUT)

            return output.decode(errors="replace")


class AABSigner(object):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        self.jarsigner = shutil.which("jarsigner") or "jarsigner"

    def sign(
        self,
        aab_path: str,
        keystore_file: str,
        keystore_password: str,
        key_alias: str,
        key_password: str = None,
    ) -> str:
        if not os.path.isfile(aab_path):
            raise FileNotFoundError(f'Unable to find file "{aab_path}"')

        sign_cmd = [
            self.jarsigner,
            "-verbose",
            "-sigalg",
            "SHA256withRSA",
            "-digestalg",
            "SHA-256",
            "-keystore",
            keystore_file,
            "-storepass",
            keystore_password,
        ]

        if key_password:
            sign_cmd.extend(["-keypass", key_password])

        sign_cmd.extend([aab_path, key_alias])

        try:
            self.logger.info("Running jarsigner command on AAB...")
            output = subprocess.check_output(sign_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"Error during sign command: {e.output.decode(errors='replace') if e.output else e}"
            )
            raise
