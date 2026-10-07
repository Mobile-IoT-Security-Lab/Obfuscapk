#!/usr/bin/env python3

import logging
import os
import re

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation


class LibEncryption(obfuscator_category.IEncryptionObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()
        self.is_adding_methods = True
        self.encryption_secret = "This-key-need-to-be-32-character"

    @staticmethod
    def _get_library_name(lines, index, register):
        for line in reversed(lines[:index]):
            stripped = line.strip()
            if stripped.startswith((".method ", ".end method")):
                break
            match = util.const_string_pattern.search(line)
            if match and match.group("register") == register:
                return match.group("string")
            if re.match(r"\s*\S+\s+" + re.escape(register) + r"(?:,|\s*$)", line):
                return None
        return None

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))
        self.encryption_secret = obfuscation_info.encryption_secret
        try:
            files_by_name = {}
            for path in obfuscation_info.get_native_lib_files():
                filename = os.path.basename(path)
                if filename.startswith("lib") and filename.endswith(".so"):
                    files_by_name.setdefault(filename[3:-3], []).append(path)

            load_pattern = re.compile(
                r"\s+invoke-static\s+{(?P<register>[vp]\d+)},\s*"
                r"Ljava/lang/System;->loadLibrary\(Ljava/lang/String;\)V"
            )
            encrypted_names = set()
            for smali_file in util.show_list_progress(
                obfuscation_info.get_smali_files(),
                interactive=obfuscation_info.interactive,
                description="Encrypting native libraries",
            ):
                with open(smali_file, "r", encoding="utf-8") as current_file:
                    lines = current_file.readlines()
                for index, line in enumerate(lines):
                    match = load_pattern.match(line)
                    if not match:
                        continue
                    name = self._get_library_name(lines, index, match.group("register"))
                    if name not in files_by_name:
                        continue
                    lines[index] = line.replace(
                        "Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V",
                        "Lcom/decryptassetmanager/DecryptAsset;->"
                        "loadEncryptedLibrary(Ljava/lang/String;)V",
                    )
                    encrypted_names.add(name)
                with open(smali_file, "w", encoding="utf-8") as current_file:
                    current_file.writelines(lines)

            if encrypted_names:
                assets_dir = obfuscation_info.get_assets_directory()
                os.makedirs(assets_dir, exist_ok=True)
                for name in sorted(encrypted_names):
                    for path in files_by_name[name]:
                        abi = os.path.basename(os.path.dirname(path))
                        destination = os.path.join(assets_dir, f"lib.{abi}.{name}.so")
                        with open(path, "rb") as source:
                            encrypted = AES.new(
                                key=self.encryption_secret.encode(), mode=AES.MODE_ECB
                            ).encrypt(pad(source.read(), AES.block_size))
                        with open(destination, "wb") as output:
                            output.write(encrypted)
                        os.remove(path)

                if not obfuscation_info.decrypt_asset_smali_file_added_flag:
                    destination = os.path.join(
                        os.path.dirname(obfuscation_info.get_smali_files()[0]),
                        "DecryptAsset.smali",
                    )
                    with open(destination, "w", encoding="utf-8") as output:
                        output.write(
                            util.get_decrypt_asset_smali_code(self.encryption_secret)
                        )
                    obfuscation_info.decrypt_asset_smali_file_added_flag = True
        except Exception as error:
            self.logger.error(
                'Error during execution of "{0}" obfuscator: {1}'.format(
                    self.__class__.__name__, error
                )
            )
            raise
        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)
