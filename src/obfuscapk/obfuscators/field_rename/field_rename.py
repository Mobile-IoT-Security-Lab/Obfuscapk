#!/usr/bin/env python3

import logging
from typing import List, Set

from obfuscapk import obfuscator_category, util
from obfuscapk.obfuscation import Obfuscation


class FieldRename(obfuscator_category.IRenameObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

        self.ignore_package_names = []

        self.is_adding_fields = False

        self.max_fields_to_add = 0
        self.added_fields = 0
        self.field_mapping = {}
        self.field_counter = 0
        self.class_superclasses = {}
        self.native_classes = set()
        self.protected_field_names: Set[str] = set()

    def rename_field(self, field_name: str) -> str:
        return util.get_length_preserved_hash(field_name)

    def get_field_key(self, class_name: str, field_name: str, field_type: str) -> str:
        return "{0}->{1}:{2}".format(class_name, field_name, field_type)

    def get_field_mapping_key(
        self, class_name: str, field_name: str, field_type: str
    ) -> str:
        while class_name:
            field_key = self.get_field_key(class_name, field_name, field_type)
            if field_key in self.field_mapping:
                return field_key
            class_name = self.class_superclasses.get(class_name)
        return ""

    def collect_superclasses(self, smali_files: List[str]):
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                class_name = None
                for line in current_file:
                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")
                    elif class_name:
                        super_match = util.super_class_pattern.search(line)
                        if super_match:
                            self.class_superclasses[class_name] = super_match.group(
                                "class_name"
                            )
                            break

    def collect_native_classes(self, smali_files: List[str]):
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                class_name = None
                for line in current_file:
                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")
                            if "JNI;" in class_name or "/Native" in class_name:
                                self.native_classes.add(class_name)
                    elif " native " in line:
                        self.native_classes.add(class_name)
                        break

    def get_ignored_smali_files(
        self, smali_files: List[str], all_smali_files: List[str]
    ) -> List[str]:
        selected_files = set(smali_files)
        return [
            smali_file
            for smali_file in all_smali_files
            if smali_file not in selected_files
        ]

    def collect_protected_field_names(self, smali_files: List[str]):
        """Protect field names that also occur in const-string instructions."""
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                for line in current_file:
                    string_match = util.const_string_pattern.search(line)
                    if string_match:
                        self.protected_field_names.add(string_match.group("string"))

    def rename_field_declarations(
        self, smali_files: List[str], interactive: bool = False
    ) -> Set[str]:
        renamed_fields: Set[str] = set()

        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming field declarations",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                skip_remaining_lines = False
                class_name = None

                for line in in_file:
                    if skip_remaining_lines:
                        out_file.write(line)
                        continue

                    ignore = False

                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if " enum " in line:
                            skip_remaining_lines = True
                            out_file.write(line)
                            continue
                        elif class_match:
                            class_name = class_match.group("class_name")

                    field_match = util.field_pattern.search(line)

                    if class_name and class_name.startswith(
                        tuple(self.ignore_package_names)
                    ):
                        ignore = True
                    elif class_name in self.native_classes:
                        ignore = True

                    if field_match:
                        old_name = field_match.group("field_name")
                        field_type = field_match.group("field_type")

                        if (
                            not ignore
                            and "$" not in old_name
                            and old_name not in self.protected_field_names
                        ):
                            mapping_key = self.get_field_key(
                                class_name, old_name, field_type
                            )

                            if mapping_key not in self.field_mapping:
                                self.field_mapping[mapping_key] = "f{0}".format(
                                    self.field_counter
                                )
                                self.field_counter += 1

                            new_name = self.field_mapping[mapping_key]

                            line = line.replace(
                                "{0}:".format(old_name),
                                "{0}:".format(new_name),
                            )
                            out_file.write(line)

                            renamed_fields.add(mapping_key)
                        else:
                            out_file.write(line)
                    else:
                        out_file.write(line)

        return renamed_fields

    def rename_field_references(
        self,
        fields_to_rename: Set[str],
        smali_files: List[str],
        interactive: bool = False,
    ):
        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming field references",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                for line in in_file:
                    field_usage_match = util.field_usage_pattern.search(line)
                    if field_usage_match:
                        field_object = field_usage_match.group("field_object")
                        old_name = field_usage_match.group("field_name")
                        field_type = field_usage_match.group("field_type")

                        mapping_key = self.get_field_mapping_key(
                            field_object, old_name, field_type
                        )

                        if (
                            mapping_key in fields_to_rename
                            and mapping_key in self.field_mapping
                        ):
                            new_name = self.field_mapping[mapping_key]
                            out_file.write(
                                line.replace(
                                    "{0}:".format(old_name),
                                    "{0}:".format(new_name),
                                )
                            )
                        else:
                            out_file.write(line)
                    else:
                        out_file.write(line)

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        self.ignore_package_names = obfuscation_info.get_ignore_package_names()

        try:
            smali_files = obfuscation_info.get_smali_files()
            all_smali_files = obfuscation_info.get_all_smali_files()
            ignored_smali_files = []
            if obfuscation_info.ignore_libs:
                ignored_smali_files = self.get_ignored_smali_files(
                    smali_files, all_smali_files
                )

            self.collect_protected_field_names(all_smali_files)
            self.collect_superclasses(smali_files)
            self.collect_native_classes(smali_files)

            renamed_field_declarations = self.rename_field_declarations(
                smali_files, obfuscation_info.interactive
            )

            self.rename_field_references(
                renamed_field_declarations,
                smali_files,
                obfuscation_info.interactive,
            )
            self.rename_field_references(
                renamed_field_declarations,
                ignored_smali_files,
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
