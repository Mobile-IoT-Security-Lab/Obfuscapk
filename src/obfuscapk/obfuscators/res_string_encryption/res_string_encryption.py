#!/usr/bin/env python3

import logging
import os
import re
import xml.etree.cElementTree as Xml
from binascii import hexlify
from typing import Set

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import pad

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation


class ResStringEncryption(obfuscator_category.IEncryptionObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        super().__init__()
        self.is_adding_methods = True

        self.encryption_secret = "This-key-need-to-be-32-character"

    def encrypt_string(self, string_to_encrypt: str) -> str:
        # This is needed to remove the escaping added by Python. For example, if we
        # find in string resources the string "\"message\"" Android will treat it as
        # "message" while in Python it's \"message\", so we need to encrypt "message"
        # and not \"message\" (we have to remove the unnecessary escaping, otherwise
        # the backslashes would by encrypted as part of the string).
        escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'", "\\": "\\"}
        string_to_encrypt = re.sub(
            r"\\(u[0-9a-fA-F]{4}|[nrt\"'\\])",
            lambda match: (
                chr(int(match.group(1)[1:], 16))
                if match.group(1).startswith("u")
                else escapes[match.group(1)]
            ),
            string_to_encrypt,
        )

        key = PBKDF2(
            password=self.encryption_secret,
            salt=self.encryption_secret.encode(),
            dkLen=32,
            count=128,
        )
        encrypted_string = hexlify(
            AES.new(key=key, mode=AES.MODE_ECB).encrypt(
                pad(string_to_encrypt.encode(errors="replace"), AES.block_size)
            )
        ).decode()
        return encrypted_string

    def encrypt_string_resources(
        self, string_resources_xml_file: str, string_names_to_encrypt: Set[str]
    ):
        xml_parser = Xml.XMLParser(encoding="utf-8")
        xml_tree = Xml.parse(string_resources_xml_file, parser=xml_parser)

        changed = False
        for xml_string in xml_tree.iter("string"):
            string_name = xml_string.get("name", None)
            string_value = "".join(xml_string.itertext())
            if string_name and string_value and string_name in string_names_to_encrypt:
                encrypted_string_value = self.encrypt_string(string_value)
                xml_string.text = encrypted_string_value
                for child in list(xml_string):
                    xml_string.remove(child)
                changed = True

        if changed:
            xml_tree.write(string_resources_xml_file, encoding="utf-8")

    def encrypt_string_array_resources(
        self,
        string_array_resources_xml_file: str,
        string_array_names_to_encrypt: Set[str],
    ):
        xml_parser = Xml.XMLParser(encoding="utf-8")
        xml_tree = Xml.parse(string_array_resources_xml_file, parser=xml_parser)

        changed = False
        for xml_string_array in xml_tree.iter("string-array"):
            string_array_name = xml_string_array.get("name", None)
            if string_array_name and string_array_name in string_array_names_to_encrypt:
                for item in xml_string_array.iter("item"):
                    value = "".join(item.itertext())
                    if value:
                        encrypted_string_value = self.encrypt_string(value)
                        item.text = encrypted_string_value
                        for child in list(item):
                            item.remove(child)
                        changed = True

        if changed:
            xml_tree.write(string_array_resources_xml_file, encoding="utf-8")

    @staticmethod
    def _get_resource_name(lines, index, register, kind, identifiers):
        constant_pattern = re.compile(
            r"\s+const(?:/16|/high16)?\s+(?P<register>[vp]\d+),\s*"
            r"(?P<value>-?(?:0x[0-9a-fA-F]+|\d+))"
        )
        for line in reversed(lines[:index]):
            if line.strip().startswith((".method ", ".end method")):
                break
            field = util.field_usage_pattern.search(line)
            if field and field.group("field_param").strip() == register:
                if (
                    field.group("usage_type") == "sget"
                    and field.group("field_type") == "I"
                    and field.group("field_object").endswith(f"/R${kind};")
                ):
                    return field.group("field_name")
                return None
            constant = constant_pattern.match(line)
            if constant and constant.group("register") == register:
                literal = constant.group("value")
                resource_id = int(literal, 16 if "x" in literal.lower() else 10)
                if "const/high16" in line and -32768 <= resource_id <= 32767:
                    resource_id <<= 16
                return identifiers.get(resource_id)
            if re.match(r"\s*\S+\s+" + re.escape(register) + r"(?:,|\s*$)", line):
                return None
        return None

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info(f'Running "{self.__class__.__name__}" obfuscator')

        self.encryption_secret = obfuscation_info.encryption_secret
        try:
            identifiers = {"string": {}, "array": {}}
            field_pattern = re.compile(
                r"\.field\s+public\s+static\s+final\s+(?P<name>\S+):I\s*=\s*"
                r"(?P<value>0x[0-9a-fA-F]+|\d+)"
            )
            for path in obfuscation_info.get_smali_files():
                kind = None
                for resource_kind in identifiers:
                    if path.endswith(f"R${resource_kind}.smali"):
                        kind = resource_kind
                        break
                if kind is None:
                    continue
                with open(path, encoding="utf-8") as source:
                    for line in source:
                        match = field_pattern.search(line)
                        if match:
                            literal = match.group("value")
                            resource_id = int(
                                literal, 16 if "x" in literal.lower() else 10
                            )
                            identifiers[kind][resource_id] = match.group("name")

            resource_files = []
            available_names = {"string": set(), "array": set()}
            for root, _, filenames in os.walk(
                obfuscation_info.get_resource_directory()
            ):
                qualifier = os.path.basename(root)
                if qualifier != "values" and not qualifier.startswith("values-"):
                    continue
                for filename in sorted(filenames):
                    if not filename.endswith(".xml"):
                        continue
                    path = os.path.join(root, filename)
                    resource_files.append(path)
                    for element in Xml.parse(path).getroot():
                        kind = "array" if element.tag == "string-array" else element.tag
                        if kind in available_names and element.get("name"):
                            available_names[kind].add(element.get("name"))

            read_pattern = re.compile(
                r"\s+invoke-virtual\s+{[vp]\d+,\s*(?P<register>[vp]\d+)},\s*"
                r"(?:Landroid/content/(?:res/Resources|Context);->"
                r"(?P<string>getString\(I\)Ljava/lang/String;)"
                r"|Landroid/content/res/Resources;->getStringArray\(I\)\[Ljava/lang/String;)"
            )
            result_pattern = re.compile(
                r"\s+move-result-object\s+(?P<register>[vp]\d+)"
            )
            encrypted_names = {"string": set(), "array": set()}
            for path in util.show_list_progress(
                obfuscation_info.get_smali_files(),
                interactive=obfuscation_info.interactive,
                description="Encrypting string resources",
            ):
                with open(path, encoding="utf-8") as source:
                    lines = source.readlines()
                for index, line in enumerate(lines):
                    match = read_pattern.match(line)
                    if not match:
                        continue
                    kind = "string" if match.group("string") else "array"
                    name = self._get_resource_name(
                        lines, index, match.group("register"), kind, identifiers[kind]
                    )
                    if name not in available_names[kind]:
                        continue
                    for result_index in range(index + 1, len(lines)):
                        following = lines[result_index].strip()
                        if not following or following.startswith(
                            ("#", ".line ", ".local ", ".end local", ".restart local")
                        ):
                            continue
                        result = result_pattern.match(lines[result_index])
                        if result:
                            register = result.group("register")
                            decrypt_method = (
                                "decryptString"
                                if kind == "string"
                                else "decryptStringArray"
                            )
                            value_type = (
                                "Ljava/lang/String;"
                                if kind == "string"
                                else "[Ljava/lang/String;"
                            )
                            # A single-register range also handles high parameter registers.
                            lines[result_index] += (
                                f"\n\tinvoke-static/range {{{register} .. {register}}},"
                                f" Lcom/decryptstringmanager/DecryptString;->{decrypt_method}({value_type}){value_type}\n\n\tmove-result-object"
                                f" {register}\n"
                            )
                            encrypted_names[kind].add(name)
                        break
                with open(path, "w", encoding="utf-8") as output:
                    output.writelines(lines)

            for path in resource_files:
                self.encrypt_string_resources(path, encrypted_names["string"])
                self.encrypt_string_array_resources(path, encrypted_names["array"])

            if (
                any(encrypted_names.values())
                and not obfuscation_info.decrypt_string_smali_file_added_flag
            ):
                destination = os.path.join(
                    os.path.dirname(obfuscation_info.get_smali_files()[0]),
                    "DecryptString.smali",
                )
                with open(destination, "w", encoding="utf-8") as output:
                    output.write(
                        util.get_decrypt_string_smali_code(self.encryption_secret)
                    )
                obfuscation_info.decrypt_string_smali_file_added_flag = True
        except Exception as error:
            self.logger.error(
                'Error during execution of "%s": %s', self.__class__.__name__, error
            )
            raise
        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)
