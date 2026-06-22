#!/usr/bin/env python3

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile


class BundleDecompiler(object):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )

        self.baksmali = os.environ.get("BAKSMALI_PATH", "/opt/smali/baksmali.jar")
        self.smali = os.environ.get("SMALI_PATH", "/opt/smali/smali.jar")
        self.aapt2 = os.environ.get("AAPT2_PATH", "aapt2")
        self.apktool = os.environ.get("APKTOOL_PATH", "apktool")

    def decode(
        self, aab_path: str, output_dir_path: str = None, force: bool = False
    ) -> str:
        if not os.path.isfile(aab_path):
            self.logger.error('Unable to find file "{0}"'.format(aab_path))
            raise FileNotFoundError('Unable to find file "{0}"'.format(aab_path))

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

        if os.path.isdir(output_dir_path):
            if force:
                shutil.rmtree(output_dir_path)
            else:
                self.logger.error(
                    'Output directory "{0}" already exists, use the "force" flag '
                    "to overwrite".format(output_dir_path)
                )
                raise FileExistsError(
                    'Output directory "{0}" already exists, use the "force" flag '
                    "to overwrite".format(output_dir_path)
                )

        self.logger.info(f"Extracting AAB directly to {output_dir_path}...")
        with zipfile.ZipFile(aab_path, "r") as zip_ref:
            zip_ref.extractall(output_dir_path)

        manifest_path = os.path.join(
            output_dir_path, "base", "manifest", "AndroidManifest.xml"
        )

        # DECODE the AndroidManifest.xml to plain XML for the plugins
        if os.path.exists(manifest_path):
            self.logger.info("Converting protobuf AndroidManifest.xml to plain XML...")
            temp_proto_apk = os.path.join(output_dir_path, "temp_proto.apk")
            temp_binary_apk = os.path.join(output_dir_path, "temp_binary.apk")
            temp_decoded_dir = os.path.join(output_dir_path, "decoded_manifest")

            # Create base prorto APK
            temp_proto_dir = os.path.join(output_dir_path, "temp_proto_dir")
            os.makedirs(temp_proto_dir, exist_ok=True)

            shutil.move(
                manifest_path, os.path.join(temp_proto_dir, "AndroidManifest.xml")
            )

            resources_pb_path = os.path.join(output_dir_path, "base", "resources.pb")
            if os.path.exists(resources_pb_path):
                shutil.copy(
                    resources_pb_path, os.path.join(temp_proto_dir, "resources.pb")
                )

            res_dir = os.path.join(output_dir_path, "base", "res")
            if os.path.exists(res_dir):
                shutil.move(res_dir, os.path.join(temp_proto_dir, "res"))

            temp_zip_path = shutil.make_archive(temp_proto_apk, "zip", temp_proto_dir)
            shutil.move(temp_zip_path, temp_proto_apk)

            shutil.rmtree(temp_proto_dir)

            # Convert proto APK to binary APK using aapt2
            subprocess.check_call(
                [
                    self.aapt2,
                    "convert",
                    "-o",
                    temp_binary_apk,
                    "--output-format",
                    "binary",
                    temp_proto_apk,
                ],
                stderr=subprocess.STDOUT,
            )

            # Decode binary APK using apktool to get plain XML manifest
            subprocess.check_call(
                [
                    self.apktool,
                    "d",
                    "--frame-path",
                    tempfile.gettempdir(),
                    temp_binary_apk,
                    "-o",
                    temp_decoded_dir,
                    "-s",
                    "-f",
                ],
                stderr=subprocess.STDOUT,
            )

            # Move the plain XML manifest and res/ to the root
            shutil.move(
                os.path.join(temp_decoded_dir, "AndroidManifest.xml"),
                os.path.join(output_dir_path, "AndroidManifest.xml"),
            )
            decoded_res = os.path.join(temp_decoded_dir, "res")
            base_res = os.path.join(output_dir_path, "base", "res")
            if os.path.exists(decoded_res):
                if os.path.exists(base_res):
                    shutil.rmtree(base_res)
                shutil.move(decoded_res, base_res)

            os.remove(temp_proto_apk)
            os.remove(temp_binary_apk)

        # Decompile the dex files one by one using baksmali
        dex_dir = os.path.join(output_dir_path, "base", "dex")
        if os.path.exists(dex_dir):
            for dex_file in os.listdir(dex_dir):
                if dex_file.endswith(".dex"):
                    dex_path = os.path.join(dex_dir, dex_file)

                    smali_folder = (
                        "smali"
                        if dex_file == "classes.dex"
                        else f"smali_{dex_file.split('.')[0]}"
                    )
                    smali_dir = os.path.join(output_dir_path, smali_folder)

                    cmd = [
                        "java",
                        "-jar",
                        self.baksmali,
                        "d",
                        "--api",
                        "30",
                        dex_path,
                        "-o",
                        smali_dir,
                    ]
                    self.logger.info(f"Disassembling {dex_file} -> {smali_folder}...")
                    subprocess.check_call(cmd, stderr=subprocess.STDOUT)

                    os.remove(dex_path)

        return output_dir_path

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
                f"{os.path.basename(source_dir_path)}.aab",
            )
            self.logger.debug(
                "No output aab path provided, the new aab will be saved in the "
                'default path: "{0}"'.format(output_aab_path)
            )

        os.makedirs(os.path.dirname(output_aab_path), exist_ok=True)

        dex_dir = os.path.join(source_dir_path, "base", "dex")
        os.makedirs(dex_dir, exist_ok=True)

        # Recompile the smali file one by one into dex using smali
        for folder in os.listdir(source_dir_path):
            folder_path = os.path.join(source_dir_path, folder)
            if folder.startswith("smali") and os.path.isdir(folder_path):
                dex_name = (
                    "classes.dex"
                    if folder == "smali"
                    else f"{folder.replace('smali_', '')}.dex"
                )
                dex_path = os.path.join(dex_dir, dex_name)

                cmd = [
                    "java",
                    "-jar",
                    self.smali,
                    "a",
                    "--api",
                    "30",
                    folder_path,
                    "-o",
                    dex_path,
                ]
                self.logger.info(f"Assembling {folder} -> {dex_name}...")
                subprocess.check_call(cmd, stderr=subprocess.STDOUT)

                shutil.rmtree(folder_path)

        root_manifest = os.path.join(source_dir_path, "AndroidManifest.xml")
        base_res = os.path.join(source_dir_path, "base", "res")
        temp_decoded_dir = os.path.join(source_dir_path, "decoded_manifest")

        # Copy back the updated manifest to the original location as protobuf

        self.logger.info(
            "Converting plain XML AndroidManifest.xml and res/ back to protobuf..."
        )
        # Move manifest and res
        shutil.move(
            root_manifest, os.path.join(temp_decoded_dir, "AndroidManifest.xml")
        )
        decoded_res = os.path.join(temp_decoded_dir, "res")
        if os.path.exists(base_res):
            if os.path.exists(decoded_res):
                shutil.rmtree(decoded_res)
            shutil.move(base_res, decoded_res)

        temp_modified_binary = os.path.join(source_dir_path, "temp_modified_binary.apk")
        temp_modified_proto = os.path.join(source_dir_path, "temp_modified_proto.apk")

        # Build the binary APK using apktool
        subprocess.check_call(
            [
                self.apktool,
                "b",
                "--frame-path",
                tempfile.gettempdir(),
                temp_decoded_dir,
                "-o",
                temp_modified_binary,
            ],
            stderr=subprocess.STDOUT,
        )

        # 3. Convert it back to proto using aapt2
        subprocess.check_call(
            [
                self.aapt2,
                "convert",
                "-o",
                temp_modified_proto,
                "--output-format",
                "proto",
                temp_modified_binary,
            ],
            stderr=subprocess.STDOUT,
        )

        # Extract the compiled protobuf AndroidManifest.xml, res/ and resources.pb
        if os.path.exists(base_res):
            shutil.rmtree(base_res)
        with zipfile.ZipFile(temp_modified_proto, "r") as z:
            z.extract(
                "AndroidManifest.xml",
                path=os.path.join(source_dir_path, "base", "manifest"),
            )

            if "resources.pb" in z.namelist():
                z.extract("resources.pb", path=os.path.join(source_dir_path, "base"))

            for file_info in z.infolist():
                if file_info.filename.startswith("res/"):
                    z.extract(file_info, os.path.join(source_dir_path, "base"))

        os.remove(temp_modified_binary)
        os.remove(temp_modified_proto)
        shutil.rmtree(temp_decoded_dir)
        if os.path.exists(root_manifest):
            os.remove(root_manifest)

        # Remove only the signature files
        meta_inf_dir = os.path.join(source_dir_path, "META-INF")
        if os.path.exists(meta_inf_dir):
            self.logger.info("Stripping old META-INF signatures...")
            for file in os.listdir(meta_inf_dir):
                if (
                    file.endswith((".SF", ".RSA", ".DSA", ".EC"))
                    or file == "MANIFEST.MF"
                ):
                    os.remove(os.path.join(meta_inf_dir, file))

        self.logger.info("Zipping final AAB...")
        output_abs_path = os.path.abspath(output_aab_path)

        # Zip back everything
        with zipfile.ZipFile(output_aab_path, "w") as zipf:
            for root, _, files in os.walk(source_dir_path):
                for file in files:
                    file_path = os.path.abspath(os.path.join(root, file))

                    if file_path == output_abs_path:
                        continue

                    arcname = os.path.relpath(file_path, source_dir_path)

                    if file.endswith(".pb") or file.endswith(".so"):
                        zipf.write(file_path, arcname, compress_type=zipfile.ZIP_STORED)
                    else:
                        zipf.write(
                            file_path, arcname, compress_type=zipfile.ZIP_DEFLATED
                        )

        return output_aab_path


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
