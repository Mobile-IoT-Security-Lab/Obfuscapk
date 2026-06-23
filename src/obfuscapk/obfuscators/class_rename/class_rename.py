#!/usr/bin/env python3

import json
import logging
import os
import re
import xml.etree.cElementTree as Xml
from typing import Dict, List, Set, Union
from xml.etree.cElementTree import Element

from obfuscapk import obfuscator_category, util
from obfuscapk.obfuscation import Obfuscation


class ClassRename(obfuscator_category.IRenameObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

        self.subclass_name_pattern = re.compile(
            r'\s+name\s=\s"(?P<subclass_name>\S+?)"', re.UNICODE
        )

        self.string_pattern = re.compile(r'"(?P<string_value>\S+?)"', re.UNICODE)

        self.split_class_pattern = re.compile(r"[/$]")

        self.package_name: Union[str, None] = None
        self.encrypted_package_name: Union[str, None] = None
        self.ignore_package_names = []

        # Will be populated before running the class rename obfuscator.
        self.class_name_to_smali_file: dict = {}

        # Track all encrypted class names to detect and resolve collisions.
        self._used_encrypted_names: Set[str] = set()
        self._reserved_class_names: Set[str] = set()

    def encrypt_identifier(self, identifier: str) -> str:
        return util.get_length_preserved_hash(identifier)

    def slash_to_dot_notation_for_classes(
        self, rename_transformations: Dict[str, str]
    ) -> Dict[str, str]:
        dot_rename_transformations: Dict[str, str] = {}

        # Remove leading L and trailing ; from class names and replace / and $ with .
        for old_name, new_name in rename_transformations.items():
            dot_rename_transformations[
                old_name[1:-1].replace("/", ".").replace("$", ".")
            ] = new_name[1:-1].replace("/", ".").replace("$", ".")

        return dot_rename_transformations

    def transform_package_name(self, manifest_xml_root: Element):
        self.encrypted_package_name = ".".join(
            [self.encrypt_identifier(token) for token in self.package_name.split(".")]
        )

        # Rename package name in manifest file.
        manifest_xml_root.set("package", self.encrypted_package_name)
        manifest_xml_root.set(
            "{http://schemas.android.com/apk/res/android}sharedUserId",
            "{0}.uid.shared".format(util.get_random_string(16)),
        )

    def get_class_ignore_prefixes(self) -> tuple:
        prefixes = []
        for package_name in self.ignore_package_names:
            if not package_name:
                continue
            if package_name.startswith("L"):
                prefixes.append(package_name)
            else:
                prefixes.append("L{0}".format(package_name))

        return tuple(prefixes)

    def get_all_smali_files(self, obfuscation_info: Obfuscation) -> List[str]:
        smali_files = obfuscation_info.get_smali_files()
        return list(getattr(obfuscation_info, "_all_smali_files", smali_files))

    def rename_class_declarations(
        self, smali_files: List[str], interactive: bool = False
    ) -> dict:
        renamed_classes = {}
        ignore_class_prefixes = self.get_class_ignore_prefixes()

        # Search for class declarations that can be renamed.
        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming class declarations",
        ):
            annotation_flag = False
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                skip_remaining_lines = False
                class_name = None
                r_class = False
                for line in in_file:
                    if skip_remaining_lines:
                        out_file.write(line)
                        continue

                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")

                            ignore_class = class_name and class_name.startswith(
                                ignore_class_prefixes
                            )

                            # Split class name to its components and encrypt them.
                            class_tokens = self.split_class_pattern.split(
                                class_name[1:-1]
                            )

                            encrypted_class_name = "L"
                            separator_index = 1
                            for token in class_tokens:
                                separator_index += len(token)
                                if token == "R":
                                    r_class = True
                                if token.isdigit():
                                    encrypted_class_name += (
                                        token + class_name[separator_index]
                                    )
                                elif not r_class and not ignore_class:
                                    if token.endswith("_Impl"):
                                        encrypted_token = (
                                            self.encrypt_identifier(token[:-5])
                                            + "_Impl"
                                        )
                                    else:
                                        encrypted_token = self.encrypt_identifier(token)
                                    encrypted_class_name += (
                                        encrypted_token + class_name[separator_index]
                                    )
                                else:
                                    encrypted_class_name += (
                                        token + class_name[separator_index]
                                    )
                                separator_index += 1

                            # Resolve hash collisions
                            if (
                                encrypted_class_name in self._used_encrypted_names
                                or encrypted_class_name in self._reserved_class_names
                            ) and encrypted_class_name != class_name:
                                base = encrypted_class_name[:-1] 
                                collision_counter = 2
                                candidate = f"{base}{collision_counter};"
                                while (
                                    candidate in self._used_encrypted_names
                                    or candidate in self._reserved_class_names
                                ):
                                    collision_counter += 1
                                    candidate = f"{base}{collision_counter};"
                                self.logger.warning(
                                    "Hash collision detected: %s -> %s "
                                    "already used, resolved to %s",
                                    class_name,
                                    encrypted_class_name,
                                    candidate,
                                )
                                encrypted_class_name = candidate

                            self._used_encrypted_names.add(encrypted_class_name)

                            out_file.write(
                                line.replace(class_name, encrypted_class_name)
                            )

                            renamed_classes[class_name] = encrypted_class_name
                            continue

                    if (
                        line.strip()
                        == ".annotation system Ldalvik/annotation/InnerClass;"
                    ):
                        annotation_flag = True
                        out_file.write(line)
                        continue

                    if annotation_flag and 'name = "' in line:
                        # Subclasses have to be renamed as well.
                        subclass_match = self.subclass_name_pattern.search(line)
                        if subclass_match and not r_class:
                            subclass_name = subclass_match.group("subclass_name")
                            out_file.write(
                                line.replace(
                                    subclass_name,
                                    self.encrypt_identifier(subclass_name),
                                )
                            )
                        else:
                            out_file.write(line)
                        continue

                    if line.strip() == ".end annotation":
                        annotation_flag = False
                        out_file.write(line)
                        continue

                    # Method declaration reached, no more class definitions in
                    # this file.
                    if line.startswith(".method "):
                        skip_remaining_lines = True
                        out_file.write(line)
                    else:
                        out_file.write(line)

        return renamed_classes

    def rename_class_usages_in_smali(
        self,
        smali_files: List[str],
        rename_transformations: dict,
        interactive: bool = False,
    ):
        dot_rename_transformations = self.slash_to_dot_notation_for_classes(
            rename_transformations
        )

        # Add package name.
        dot_rename_transformations[self.package_name] = self.encrypted_package_name

        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming class usages in smali files",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                for line in in_file:
                    # Rename classes used as strings with . instead of /.
                    string_match = self.string_pattern.search(line)
                    if (
                        string_match
                        and string_match.group("string_value")
                        in dot_rename_transformations
                    ):
                        line = line.replace(
                            string_match.group("string_value"),
                            dot_rename_transformations[
                                string_match.group("string_value")
                            ],
                        )

                    # Sometimes classes are used in annotations as strings
                    # without trailing ;
                    if (
                        string_match
                        and "{0};".format(string_match.group("string_value"))
                        in rename_transformations
                    ):
                        line = line.replace(
                            string_match.group("string_value"),
                            rename_transformations[
                                "{0};".format(string_match.group("string_value"))
                            ][:-1],
                        )

                    # Rename classes used with the "classic" syntax
                    # (leading L and trailing ;).
                    class_names = util.class_name_pattern.findall(line)
                    for class_name in sorted(class_names, reverse=True, key=len):
                        if class_name in rename_transformations:
                            line = line.replace(
                                class_name, rename_transformations[class_name]
                            )

                    out_file.write(line)

    def rename_class_usages_in_xml(
        self,
        xml_files: List[str],
        rename_transformations: dict,
        interactive: bool = False,
    ):
        dot_rename_transformations = self.slash_to_dot_notation_for_classes(
            rename_transformations
        )

        # Add package name.
        dot_rename_transformations[self.package_name] = self.encrypted_package_name

        # Activity names may omit the package name
        relative_rename_transformations = {}
        for old_name, new_name in dot_rename_transformations.items():
            if old_name.startswith(self.package_name):
                relative_rename_transformations[
                    old_name.replace(self.package_name, "", 1)
                ] = new_name.replace(self.encrypted_package_name, "", 1)

        xml_value_pattern = re.compile(
            r"(?P<quote>[\"'])(?P<value>[^\"']+)(?P=quote)", re.UNICODE
        )
        xml_tag_pattern = re.compile(
            r"(?P<prefix></?)(?P<tag>[A-Za-z_][A-Za-z0-9_.$]*)(?P<suffix>[\s>/])",
            re.UNICODE,
        )

        for xml_file in util.show_list_progress(
            xml_files,
            interactive=interactive,
            description="Renaming class usages in xml files",
        ):
            with open(xml_file, "r", encoding="utf-8") as current_file:
                file_content = current_file.read()

            def replace_xml_value(match):
                value = match.group("value")
                if value in dot_rename_transformations:
                    value = dot_rename_transformations[value]
                elif value in relative_rename_transformations:
                    value = relative_rename_transformations[value]

                return "{quote}{value}{quote}".format(
                    quote=match.group("quote"),
                    value=value,
                )

            def replace_xml_tag(match):
                tag = match.group("tag")
                if tag in dot_rename_transformations:
                    tag = dot_rename_transformations[tag]

                return "{prefix}{tag}{suffix}".format(
                    prefix=match.group("prefix"),
                    tag=tag,
                    suffix=match.group("suffix"),
                )

            file_content = xml_value_pattern.sub(replace_xml_value, file_content)
            file_content = xml_tag_pattern.sub(replace_xml_tag, file_content)

            with open(xml_file, "w", encoding="utf-8") as current_file:
                current_file.write(file_content)

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        try:
            smali_files = obfuscation_info.get_smali_files()
            all_smali_files = self.get_all_smali_files(obfuscation_info)

            Xml.register_namespace(
                "android", "http://schemas.android.com/apk/res/android"
            )

            xml_parser = Xml.XMLParser(encoding="utf-8")
            manifest_tree = Xml.parse(
                obfuscation_info.get_manifest_file(), parser=xml_parser
            )
            manifest_root = manifest_tree.getroot()

            self.package_name = manifest_root.get("package")
            if not self.package_name:
                raise Exception(
                    "Unable to extract package name from application manifest"
                )

            # Get a mapping between class name and smali file path.
            for smali_file in util.show_list_progress(
                all_smali_files,
                interactive=obfuscation_info.interactive,
                description="Class name to smali file mapping",
            ):
                with open(smali_file, "r", encoding="utf-8") as current_file:
                    class_name = None
                    for line in current_file:
                        if not class_name:
                            # Every smali file contains a class.
                            class_match = util.class_pattern.search(line)
                            if class_match:
                                self.class_name_to_smali_file[
                                    class_match.group("class_name")
                                ] = smali_file
                                break

            self._reserved_class_names = set(self.class_name_to_smali_file)

            self.transform_package_name(manifest_root)

            # Write the changes into the manifest file.
            manifest_tree.write(obfuscation_info.get_manifest_file(), encoding="utf-8")

            xml_files: Set[str] = set(
                os.path.join(root, file_name)
                for root, dir_names, file_names in os.walk(
                    obfuscation_info.get_resource_directory()
                )
                for file_name in file_names
                if file_name.endswith(".xml")
                and (
                    "layout" in root or "xml" in root
                )  # Only res/layout-*/ and res/xml-*/ folders.
            )
            xml_files.add(obfuscation_info.get_manifest_file())

            # TODO: use the following code to rename only the classes declared in
            #  application's package.

            # package_smali_files: Set[str] = set(
            #     smali_file
            #     for class_name, smali_file in self.class_name_to_smali_file.items()
            #     if class_name[1:].startswith(self.package_name.replace(".", "/"))
            # )
            #
            # # Rename the classes declared in the application's package.
            # class_rename_transformations = self.rename_class_declarations(
            #     list(package_smali_files), obfuscation_info.interactive
            # )

            # Get user defined ignore package list.
            self.ignore_package_names = obfuscation_info.get_ignore_package_names()

            # Rename all classes declared in smali files.
            class_rename_transformations = self.rename_class_declarations(
                smali_files, obfuscation_info.interactive
            )

            out_dir = os.path.dirname(os.path.abspath(obfuscation_info.apk_path))
            apk_name = os.path.splitext(os.path.basename(obfuscation_info.apk_path))[0]
            out_file = os.path.join(out_dir, f"{apk_name}_class_mapping.json")
            self.export_mapping(class_rename_transformations, out_file)

            # Update renamed classes through all the smali files.
            self.rename_class_usages_in_smali(
                all_smali_files,
                class_rename_transformations,
                obfuscation_info.interactive,
            )

            # Update renamed classes through all the xml files.
            self.rename_class_usages_in_xml(
                list(xml_files),
                class_rename_transformations,
                obfuscation_info.interactive,
            )

        except Exception as e:
            self.logger.error(
                'Error during execution of "{0}" obfuscator: {1}'.format(
                    self.__class__.__name__, e
                )
            )
            raise

        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)

    def export_mapping(self, mapping: dict, out_file: str):
        with open(out_file, "w") as f:
            json.dump(mapping, f, indent=4)
