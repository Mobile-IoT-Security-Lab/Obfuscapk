#!/usr/bin/env python3

import io
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import List


class Apktool(object):
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        if "APKTOOL_PATH" in os.environ:
            self.apktool_path: str = os.environ["APKTOOL_PATH"]
        else:
            self.apktool_path: str = "apktool"

        full_apktool_path = shutil.which(self.apktool_path)

        # Make sure to use the full path of the executable (needed for cross-platform
        # compatibility).
        if full_apktool_path is None:
            raise RuntimeError(
                f'Something is wrong with executable "{self.apktool_path}"'
            )
        else:
            self.apktool_path = full_apktool_path

    def decode(
        self, apk_path: str, output_dir_path: str = None, force: bool = False
    ) -> str:
        # Check if the apk file to decode is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error(f'Unable to find file "{apk_path}"')
            raise FileNotFoundError(f'Unable to find file "{apk_path}"')

        # If no output directory is specified, use a new directory in the same
        # directory as the apk file to decode.
        if not output_dir_path:
            output_dir_path = os.path.join(
                os.path.dirname(apk_path),
                os.path.splitext(os.path.basename(apk_path))[0],
            )
            self.logger.debug(
                "No output directory provided, the result will be saved in the same"
                " directory as the input file, in a directory with the same name as"
                f' the input file: "{output_dir_path}"'
            )

        # If an output directory is provided, make sure that the path to that
        # directory exists (the final directory will be created by apktool).
        elif not os.path.isdir(os.path.dirname(output_dir_path)):
            self.logger.error(
                f'Unable to find output directory "{os.path.dirname(output_dir_path)}",'
                f' apktool won\'t be able to create the directory "{output_dir_path}"'
            )
            raise NotADirectoryError(
                f'Unable to find output directory "{os.path.dirname(output_dir_path)}",'
                f' apktool won\'t be able to create the directory "{output_dir_path}"'
            )

        # Inform the user if an existing output directory is provided without the
        # "force" flag.
        if os.path.isdir(output_dir_path) and not force:
            self.logger.error(
                f'Output directory "{output_dir_path}" already exists, use the "force"'
                " flag to overwrite"
            )
            raise FileExistsError(
                f'Output directory "{output_dir_path}" already exists, use the "force"'
                " flag to overwrite"
            )

        decode_cmd: List[str] = [
            self.apktool_path,
            "d",
            "--frame-path",
            tempfile.gettempdir(),
            "-o",
            output_dir_path,
            apk_path,
        ]

        if force:
            decode_cmd.insert(4, "--force")

        try:
            self.logger.info(f"Running decode command \"{' '.join(decode_cmd)}\"")
            # A new line character is sent as input since newer versions of Apktool
            # have an interactive prompt on Windows where the user should press a key.
            output = subprocess.check_output(
                decode_cmd, stderr=subprocess.STDOUT, input=b"\n"
            ).strip()
            if b"Exception in thread " in output:
                # Report exception raised in Apktool.
                raise subprocess.CalledProcessError(1, decode_cmd, output)
            return output.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                "Error during decode command:"
                f" {e.output.decode(errors='replace') if e.output else e}"
            )
            raise
        except Exception as e:
            self.logger.error(f"Error during decoding: {e}")
            raise

    def build(self, source_dir_path: str, output_apk_path: str = None) -> str:
        # Check if the input directory exists.
        if not os.path.isdir(source_dir_path):
            self.logger.error(f'Unable to find source directory "{source_dir_path}"')
            raise NotADirectoryError(
                f'Unable to find source directory "{source_dir_path}"'
            )

        # If no output apk path is specified, the new apk will be saved in the
        # default path: <source_dir_path>/dist/<source_dir_name>.apk
        if not output_apk_path:
            output_apk_path = os.path.join(
                source_dir_path,
                "dist",
                f"{os.path.basename(source_dir_path)}.apk",
            )
            self.logger.debug(
                "No output apk path provided, the new apk will be saved in the default"
                f' path: "{output_apk_path}"'
            )

        build_cmd: List[str] = [
            self.apktool_path,
            "b",
            "--frame-path",
            tempfile.gettempdir(),
            "--force",
            "-o",
            output_apk_path,
            source_dir_path,
        ]

        try:
            self.logger.info(f"Running build command \"{' '.join(build_cmd)}\"")
            # A new line character is sent as input since newer versions of Apktool
            # have an interactive prompt on Windows where the user should press a key.
            output = subprocess.check_output(
                build_cmd, stderr=subprocess.STDOUT, input=b"\n"
            ).strip()
            if (
                b"brut.directory.PathNotExist: " in output
                or b"Exception in thread " in output
            ):
                # Report exception raised in Apktool.
                raise subprocess.CalledProcessError(1, build_cmd, output)

            if not os.path.isfile(output_apk_path):
                raise FileNotFoundError(
                    f'"{output_apk_path}" was not built correctly. Apktool'
                    f" output:\n{output.decode(errors='replace')}"
                )

            return output.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                "Error during build command:"
                f" {e.output.decode(errors='replace') if e.output else e}"
            )
            raise
        except Exception as e:
            self.logger.error(f"Error during building: {e}")
            raise


class Zipalign(object):
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        if "ZIPALIGN_PATH" in os.environ:
            self.zipalign_path: str = os.environ["ZIPALIGN_PATH"]
        else:
            self.zipalign_path: str = "zipalign"

        full_zipalign_path = shutil.which(self.zipalign_path)

        # Make sure to use the full path of the executable (needed for cross-platform
        # compatibility).
        if full_zipalign_path is None:
            raise RuntimeError(
                f'Something is wrong with executable "{self.zipalign_path}"'
            )
        else:
            self.zipalign_path = full_zipalign_path

    def align(self, apk_path: str) -> str:
        # Check if the apk file to align is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error(f'Unable to find file "{apk_path}"')
            raise FileNotFoundError(f'Unable to find file "{apk_path}"')

        # Since zipalign cannot be run inplace, a temp file will be created.
        apk_copy_path = (
            f"{os.path.join(os.path.dirname(apk_path), os.path.splitext(os.path.basename(apk_path))[0])}"
            f".copy.apk"
        )

        try:
            apk_copy_path = shutil.copy2(apk_path, apk_copy_path)

            align_cmd = [
                self.zipalign_path,
                "-p",
                "-v",
                "-f",
                "4",
                apk_copy_path,
                apk_path,
            ]

            self.logger.info(f"Running align command \"{' '.join(align_cmd)}\"")
            output = subprocess.check_output(
                align_cmd, stderr=subprocess.STDOUT
            ).strip()
            return output.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                "Error during align command:"
                f" {e.output.decode(errors='replace') if e.output else e}"
            )
            raise
        except Exception as e:
            self.logger.error(f"Error during aligning: {e}")
            raise
        finally:
            # Remove the temp file used for zipalign.
            if os.path.isfile(apk_copy_path):
                os.remove(apk_copy_path)


class ApkSigner(object):
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        if "APKSIGNER_PATH" in os.environ:
            self.apksigner_path: str = os.environ["APKSIGNER_PATH"]
        else:
            self.apksigner_path: str = "apksigner"

        full_apksigner_path = shutil.which(self.apksigner_path)

        # Make sure to use the full path of the executable (needed for cross-platform
        # compatibility).
        if full_apksigner_path is None:
            raise RuntimeError(
                f'Something is wrong with executable "{self.apksigner_path}"'
            )
        else:
            self.apksigner_path = full_apksigner_path

    def sign(
        self,
        apk_path: str,
        keystore_file_path: str,
        keystore_password: str,
        key_alias: str,
        key_password: str = None,
    ) -> str:
        # Check if the apk file to sign is a valid file.
        if not os.path.isfile(apk_path):
            self.logger.error(f'Unable to find file "{apk_path}"')
            raise FileNotFoundError(f'Unable to find file "{apk_path}"')

        sign_cmd: List[str] = [
            self.apksigner_path,
            "sign",
            "-v",
            "--ks",
            keystore_file_path,
            "--ks-key-alias",
            key_alias,
            "--ks-pass",
            f"pass:{keystore_password}",
            apk_path,
        ]

        if key_password:
            sign_cmd.insert(-1, "--key-pass")
            sign_cmd.insert(-1, f"pass:{key_password}")

        try:
            self.logger.info(f"Running sign command \"{' '.join(sign_cmd)}\"")
            output = subprocess.check_output(sign_cmd, stderr=subprocess.STDOUT).strip()
            return output.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            self.logger.error(
                "Error during sign command:"
                f" {e.output.decode(errors='replace') if e.output else e}"
            )
            raise
        except Exception as e:
            self.logger.error(f"Error during signing: {e}")
            raise

    def resign(
        self,
        apk_path: str,
        keystore_file_path: str,
        keystore_password: str,
        key_alias: str,
        key_password: str = None,
    ) -> str:
        # If present, delete the old signature of the apk and then sign it with the
        # new signature. Since Python doesn't allow directly deleting a file inside an
        # archive, an OS independent solution is to create a new archive without
        # including the signature files.

        def is_signature_file(filename: str) -> bool:
            filename = filename.upper()
            if not filename.startswith("META-INF/"):
                return False

            filename = filename[len("META-INF/") :]
            return "/" not in filename and (
                filename == "MANIFEST.MF"
                or filename.endswith((".SF", ".RSA", ".DSA", ".EC"))
            )

        try:
            unsigned_apk_buffer = io.BytesIO()

            with zipfile.ZipFile(apk_path, "r") as current_apk:
                # Check if the current apk is already signed.
                if any(
                    is_signature_file(entry.filename)
                    for entry in current_apk.infolist()
                ):
                    self.logger.info(
                        f'Removing current signature from apk "{apk_path}"'
                    )

                    # Create a new in-memory archive without the signature.
                    with zipfile.ZipFile(
                        unsigned_apk_buffer, "w"
                    ) as unsigned_apk_zip_buffer:
                        for entry in current_apk.infolist():
                            if not is_signature_file(entry.filename):
                                unsigned_apk_zip_buffer.writestr(
                                    entry, current_apk.read(entry.filename)
                                )

                    # Write the in-memory archive to disk.
                    with open(apk_path, "wb") as unsigned_apk:
                        unsigned_apk.write(unsigned_apk_buffer.getvalue())

        except Exception as e:
            self.logger.error(f"Error during the removal of the old signature: {e}")
            raise

        return self.sign(
            apk_path, keystore_file_path, keystore_password, key_alias, key_password
        )
