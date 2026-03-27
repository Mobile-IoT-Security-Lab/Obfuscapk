#!/usr/bin/env python3

import logging
from typing import List, Set

from obfuscapk import obfuscator_category
from obfuscapk import util
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

    def rename_field(self, field_name: str) -> str:
        return util.get_length_preserved_hash(field_name)

    def get_sdk_class_names(self, smali_files: List[str]) -> Set[str]:
        class_names: Set[str] = set()
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                for line in current_file:
                    class_match = util.class_pattern.search(line)
                    if class_match:
                        if class_match.group("class_name").startswith(
                            ("Landroid", "Ljava")
                        ):
                            class_names.add(class_match.group("class_name"))
                        break
        return class_names

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
                class_name = None

                for line in in_file:
                    ignore = False

                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")

                    field_match = util.field_pattern.search(line)

                    if class_name and class_name.startswith(
                        tuple("L{0}".format(p) for p in self.ignore_package_names)
                    ):
                        ignore = True

                    if field_match:
                        old_name = field_match.group("field_name")
                        field_type = field_match.group("field_type")
                        
                        if not ignore and "$" not in old_name:
                            mapping_key = "{0}:{1}".format(old_name, field_type)
                            
                            if mapping_key not in self.field_mapping:
                                self.field_mapping[mapping_key] = "f{0}".format(self.field_counter)
                                self.field_counter += 1
                                
                            new_name = self.field_mapping[mapping_key]
                            
                            line = line.replace(
                                "{0}:".format(old_name),
                                "{0}:".format(new_name),
                            )
                            out_file.write(line)

                            renamed_fields.add("{0}->{1}:{2}".format(class_name, old_name, field_type))
                        else:
                            out_file.write(line)
                    else:
                        out_file.write(line)

        return renamed_fields

    def rename_field_references(
        self,
        fields_to_rename: Set[str],
        smali_files: List[str],
        sdk_classes: Set[str],
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
                        old_name = field_usage_match.group("field_name")
                        field_type = field_usage_match.group("field_type")
                        
                        mapping_key = "{0}:{1}".format(old_name, field_type)
                        
                        if mapping_key in self.field_mapping:
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
            sdk_class_declarations = self.get_sdk_class_names(
                obfuscation_info.get_smali_files()
            )
            renamed_field_declarations = self.rename_field_declarations(
                obfuscation_info.get_smali_files(), obfuscation_info.interactive
            )

            self.rename_field_references(
                renamed_field_declarations,
                obfuscation_info.get_smali_files(),
                sdk_class_declarations,
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
