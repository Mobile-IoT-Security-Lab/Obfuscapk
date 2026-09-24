#!/usr/bin/env python3

from codecs import ignore_errors
from doctest import IGNORE_EXCEPTION_DETAIL
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

        # Classes that may be renamed, but must remain in their original dex
        # package to preserve package-sensitive access from a kept class.
        self.package_preserved_class_names: Set[str] = set()

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

    def get_class_names_to_ignore(self, obfuscation_info: Obfuscation, manifest_root: Element) -> Set[str]:

        ignored_class_names = set()

        # Ignore JNI and native classes
        for class_name, smali_file in self.class_name_to_smali_file.items():
            if "JNI;" in class_name or "/Native" in class_name:
                ignored_class_names.add(class_name)
            with open(smali_file, "r", encoding="utf-8") as current_file:
                if any(" native " in line for line in current_file):
                    ignored_class_names.add(class_name)

        # Ignore classes referenced in the manifest
        package_name = manifest_root.get("package", "")
        for element in manifest_root.iter():
            for value in element.attrib.values():
                candidates = [value]
                if value.startswith("."):
                    candidates.append(package_name + value)
                elif "." not in value:
                    candidates.append("{}.{}".format(package_name, value))
                for candidate in candidates:
                    smali_class_name = "L{};".format(
                        candidate.replace(".", "/")
                    )
                    if smali_class_name in self.class_name_to_smali_file:
                        ignored_class_names.add(smali_class_name)

        # Ignore native library references
        native_names = set()
        native_name_pattern = re.compile(
            rb"[A-Za-z_$][A-Za-z0-9_$]*(?:[/.][A-Za-z_$][A-Za-z0-9_$]*)+"
        )
        for native_lib_file in obfuscation_info.get_native_lib_files():
            with open(native_lib_file, "rb") as native_lib:
                native_names.update(
                    name.replace(b".", b"/")
                    for name in native_name_pattern.findall(native_lib.read())
                )

        ignored_class_names.update(
            class_name
            for class_name in self.class_name_to_smali_file
            if class_name[1:-1].encode() in native_names
            or class_name[:-1].encode() in native_names
        )

        return ignored_class_names

    def package_sensitive_dependencies(self, roots: Set[str]) -> Set[str]:
        dependencies = {
            class_name: set() for class_name in self.class_name_to_smali_file
        }

        restricted_classes = set(self.class_name_to_smali_file)
        restricted_methods = set()
        restricted_fields = set()

        def is_package_sensitive(line: str) -> bool:
            flags = line.split()
            return "public" not in flags and "private" not in flags

        for class_name, smali_file in self.class_name_to_smali_file.items():
            with open(smali_file, "r", encoding="utf-8") as current_file:
                for line in current_file:
                    # Looks for method declarations
                    method = util.method_pattern.search(line)
                    if method and is_package_sensitive(line):
                        restricted_methods.add(
                            (
                                class_name,
                                method.group("method_name"),
                                method.group("method_param"),
                                method.group("method_return"),
                            )
                        )
                    # Looks for field declarations
                    field = util.field_pattern.search(line)
                    if field and is_package_sensitive(line):
                        restricted_fields.add(
                            (
                                class_name,
                                field.group("field_name"),
                                field.group("field_type"),
                            )
                        )


        def connect(first: str, second: str) -> None:
            if (
                first != second
                and second in self.class_name_to_smali_file
                and first.rsplit("/", 1)[0] == second.rsplit("/", 1)[0]
            ):
                dependencies[first].add(second)
                dependencies[second].add(first)

        # Connect classes based on package-sensitive access
        for class_name, smali_file in self.class_name_to_smali_file.items():
            with open(smali_file, "r", encoding="utf-8") as current_file:
                for line in current_file:
                    for referenced_class in util.class_name_pattern.findall(line):
                        if referenced_class in restricted_classes:
                            connect(class_name, referenced_class)

                    invocation = util.invoke_pattern.search(line)
                    if invocation and (
                        invocation.group("invoke_object"),
                        invocation.group("invoke_method"),
                        invocation.group("invoke_param"),
                        invocation.group("invoke_return"),
                    ) in restricted_methods:
                        connect(class_name, invocation.group("invoke_object"))

                    field_usage = util.field_usage_pattern.search(line)
                    if field_usage and (
                        field_usage.group("field_object"),
                        field_usage.group("field_name"),
                        field_usage.group("field_type"),
                    ) in restricted_fields:
                        connect(class_name, field_usage.group("field_object"))

        # Search connected classes in the graph
        result = set(roots)
        pending = list(roots)
        while pending:
            for dependency in dependencies.get(pending.pop(), ()):
                if dependency not in result:
                    result.add(dependency)
                    pending.append(dependency)
        return result

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
                            preserve_package = (
                                class_name in self.package_preserved_class_names
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
                                is_package_token = (
                                    class_name[separator_index] == "/"
                                )
                                if token.isdigit():
                                    encrypted_class_name += (
                                        token + class_name[separator_index]
                                    )
                                elif (
                                    not r_class
                                    and not ignore_class
                                    and not (preserve_package and is_package_token)
                                ):
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
                        if subclass_match and not r_class and not ignore_class:
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
        manifest_file: Union[str, None] = None,
    ):
        dot_rename_transformations = self.slash_to_dot_notation_for_classes(
            rename_transformations
        )

        # Add package name.
        dot_rename_transformations[self.package_name] = self.encrypted_package_name

        if manifest_file:
            manifest_root = Xml.parse(manifest_file).getroot()
            android_name = "{http://schemas.android.com/apk/res/android}name"
            package_prefix = "{0}.".format(self.package_name)
            encrypted_package_prefix = "{0}.".format(self.encrypted_package_name)
            for alias in manifest_root.iter("activity-alias"):
                alias_name = alias.get(android_name)
                if alias_name and alias_name.startswith(package_prefix):
                    dot_rename_transformations[alias_name] = (
                        encrypted_package_prefix
                        + alias_name[len(package_prefix) :]
                    )

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

    def get_resource_xml_files(self, resource_directory: str) -> List[str]:
        xml_files = []
        for root, _, file_names in os.walk(resource_directory):
            for file_name in file_names:
                if file_name.endswith(".xml"):
                    xml_files.append(os.path.join(root, file_name))
        return xml_files

    def rename_class_usages_in_json_assets(
        self, assets_directory: str, rename_transformations: Dict[str, str]
    ) -> None:
        class_names = dict(rename_transformations)
        for old_name, new_name in rename_transformations.items():
            class_names[old_name[1:-1]] = new_name[1:-1]
            class_names[old_name[1:-1].replace("/", ".")] = new_name[1:-1].replace(
                "/", "."
            )

        def rename_json_value(value):
            if isinstance(value, str):
                renamed_value = class_names.get(value, value)
                return renamed_value, renamed_value != value
            if isinstance(value, list):
                renamed_items = [rename_json_value(item) for item in value]
                return [item for item, _ in renamed_items], any(
                    changed for _, changed in renamed_items
                )
            if isinstance(value, dict):
                renamed_items = {
                    key: rename_json_value(item) for key, item in value.items()
                }
                return {
                    key: item for key, (item, _) in renamed_items.items()
                }, any(changed for _, changed in renamed_items.values())
            return value, False

        json_files = []
        for root, _, file_names in os.walk(assets_directory):
            for file_name in file_names:
                if file_name.lower().endswith(".json"):
                    json_files.append(os.path.join(root, file_name))

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as current_file:
                    content = json.load(current_file)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            content, changed = rename_json_value(content)
            if changed:
                with open(json_file, "w", encoding="utf-8") as current_file:
                    json.dump(content, current_file, indent=2)
                    current_file.write("\n")

    def get_service_loader_files(self, decoded_apk_directory: str) -> List[str]:
        service_files = []
        for root, _, file_names in os.walk(decoded_apk_directory):
            relative_root = os.path.relpath(root, decoded_apk_directory)
            path_parts = os.path.normpath(relative_root).split(os.path.sep)
            if len(path_parts) < 2 or path_parts[-2:] != ["META-INF", "services"]:
                continue
            path_prefix = path_parts[:-2]
            if path_prefix and path_prefix[-1] not in {
                "unknown",
                "original",
                "root",
            }:
                continue
            service_files.extend(
                os.path.join(root, file_name) for file_name in file_names
            )
        return service_files

    def rename_class_usages_in_service_loader_files(
        self,
        decoded_apk_directory: str,
        rename_transformations: Dict[str, str],
    ) -> None:
        binary_name_transformations = {
            old_name[1:-1].replace("/", "."): new_name[1:-1].replace("/", ".")
            for old_name, new_name in rename_transformations.items()
        }
        renamed_descriptors = {}
        service_operations = []
        destination_files = set()

        for service_file in sorted(
            self.get_service_loader_files(decoded_apk_directory)
        ):
            service_name = os.path.basename(service_file)
            renamed_service_name = binary_name_transformations.get(
                service_name, service_name
            )
            renamed_service_file = os.path.join(
                os.path.dirname(service_file), renamed_service_name
            )
            if renamed_service_file != service_file and (
                os.path.exists(renamed_service_file)
                or renamed_service_file in destination_files
            ):
                raise FileExistsError(
                    'Unable to rename service descriptor "{0}" to "{1}": '
                    "destination already exists".format(
                        service_file, renamed_service_file
                    )
                )
            destination_files.add(renamed_service_file)
            service_operations.append(
                (service_file, service_name, renamed_service_file, renamed_service_name)
            )

        for (
            service_file,
            service_name,
            renamed_service_file,
            renamed_service_name,
        ) in service_operations:
            with open(service_file, "r", encoding="utf-8") as current_file:
                lines = current_file.readlines()

            changed = False
            renamed_lines = []
            for line in lines:
                provider_part, comment_marker, comment = line.partition("#")
                provider_name = provider_part.strip()
                renamed_provider = binary_name_transformations.get(provider_name)
                if renamed_provider and renamed_provider != provider_name:
                    leading_size = len(provider_part) - len(provider_part.lstrip())
                    trailing_start = len(provider_part.rstrip())
                    provider_part = (
                        provider_part[:leading_size]
                        + renamed_provider
                        + provider_part[trailing_start:]
                    )
                    changed = True
                renamed_lines.append(provider_part + comment_marker + comment)

            if changed:
                with open(service_file, "w", encoding="utf-8") as current_file:
                    current_file.writelines(renamed_lines)

            if renamed_service_name == service_name:
                continue

            os.rename(service_file, renamed_service_file)
            renamed_descriptors[service_name] = renamed_service_name

        apktool_config = os.path.join(decoded_apk_directory, "apktool.yml")
        if renamed_descriptors and os.path.isfile(apktool_config):
            with open(apktool_config, "r", encoding="utf-8") as current_file:
                config_content = current_file.read()

            for old_name, new_name in renamed_descriptors.items():
                config_content = config_content.replace(
                    "META-INF/services/{0}".format(old_name),
                    "META-INF/services/{0}".format(new_name),
                )

            with open(apktool_config, "w", encoding="utf-8") as current_file:
                current_file.write(config_content)

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        try:
            smali_files = obfuscation_info.get_smali_files()
            all_smali_files = obfuscation_info.get_all_smali_files()

            Xml.register_namespace(
                "android", "http://schemas.android.com/apk/res/android"
            )
            # Get the manifest root element
            xml_parser = Xml.XMLParser(encoding="utf-8")
            manifest_tree = Xml.parse(
                obfuscation_info.get_manifest_file(), parser=xml_parser
            )
            manifest_root = manifest_tree.getroot()

            # Get the package name from the manifest root element
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

            # Prevent accidental hash collision with unrenamed class names
            self._reserved_class_names = set(self.class_name_to_smali_file)

            # Get class names to ignore
            self.ignore_package_names = obfuscation_info.get_ignore_package_names()
            ignored_class_names = self.get_class_names_to_ignore(obfuscation_info, manifest_root)
            self.ignore_package_names.extend(
                ignored_class_names
            )

            # Get package-sensitive dependencies which package name cannot be renamed
            package_sensitive_dependencies = self.package_sensitive_dependencies(ignored_class_names)
            self.package_preserved_class_names = (
                package_sensitive_dependencies - ignored_class_names
            )
            self.transform_package_name(manifest_root)

            # Write the changes into the manifest file.
            manifest_tree.write(obfuscation_info.get_manifest_file(), encoding="utf-8")

            xml_files = self.get_resource_xml_files(
                obfuscation_info.get_resource_directory()
            )
            xml_files.append(obfuscation_info.get_manifest_file())

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

            # Rename all classes declared in smali files.
            class_rename_transformations = self.rename_class_declarations(
                smali_files, obfuscation_info.interactive
            )

            out_dir = os.path.dirname(os.path.abspath(obfuscation_info.apk_path))
            apk_name = os.path.splitext(os.path.basename(obfuscation_info.apk_path))[0]
            out_file = os.path.join(out_dir, f"{apk_name}_class_mapping.json")
            self.export_mapping(class_rename_transformations, out_file)

            self.rename_class_usages_in_json_assets(
                obfuscation_info.get_assets_directory(),
                class_rename_transformations,
            )

            self.rename_class_usages_in_service_loader_files(
                os.path.dirname(obfuscation_info.get_manifest_file()),
                class_rename_transformations,
            )

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
                manifest_file=obfuscation_info.get_manifest_file(),
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
