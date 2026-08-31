#!/usr/bin/env python3

import json
import logging
import os
from typing import List, Set

from obfuscapk import obfuscator_category, util
from obfuscapk.obfuscation import Obfuscation


class MethodRename(obfuscator_category.IRenameObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

        self.ignore_package_names = []
        self.method_mapping = {}
        self.method_counter = 0

    def rename_method(self, method_name: str) -> str:
        return util.get_length_preserved_hash(method_name)

    def rename_method_declarations(
        self,
        smali_files: List[str],
        class_names_to_ignore: Set[str],
        interactive: bool = False,
    ) -> Set[str]:
        renamed_methods: Set[str] = set()

        # Search for method definitions that can be renamed.
        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming method declarations",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                skip_remaining_lines = False
                class_name = None

                for line in in_file:
                    if skip_remaining_lines:
                        out_file.write(line)
                        continue

                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if " enum " in line:
                            skip_remaining_lines = True
                            out_file.write(line)
                            continue
                        elif class_match:
                            class_name = class_match.group("class_name")
                            if (
                                class_name in class_names_to_ignore
                                or class_name.startswith(tuple(self.ignore_package_names))
                            ):
                                skip_remaining_lines = True
                            out_file.write(line)
                            continue

                    method_match = util.method_pattern.search(line)
                    if (
                        method_match
                        and " private " in line
                        and "<init>" not in line
                        and "<clinit>" not in line
                        and " native " not in line
                        and " abstract " not in line
                        and " access$" not in line
                        and " synthetic " not in line
                    ):
                        old_name = method_match.group("method_name")
                        params = method_match.group("method_param")
                        returns = method_match.group("method_return")

                        full_signature = f"{class_name}->{old_name}({params}){returns}"
                        if full_signature not in self.method_mapping:
                            self.method_mapping[full_signature] = f"m{self.method_counter}"
                            self.method_counter += 1

                        new_name = self.method_mapping[full_signature]

                        out_file.write(
                            line.replace(
                                "{0}(".format(old_name),
                                "{0}(".format(new_name),
                            )
                        )
                        renamed_methods.add(full_signature)
                    else:
                        out_file.write(line)

        return renamed_methods

    def rename_method_invocations(
        self,
        smali_files: List[str],
        methods_to_rename: Set[str],
        interactive: bool = False,
    ):
        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming method invocations",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                for line in in_file:
                    invoke_match = util.invoke_pattern.search(line)
                    if invoke_match:
                        old_name = invoke_match.group("invoke_method")
                        params = invoke_match.group("invoke_param")
                        returns = invoke_match.group("invoke_return")

                        owner = invoke_match.group("invoke_object")
                        mapping_key = f"{owner}->{old_name}({params}){returns}"

                        if mapping_key in methods_to_rename:
                            new_name = self.method_mapping[mapping_key]

                            out_file.write(
                                line.replace(
                                    "->{0}(".format(old_name),
                                    "->{0}(".format(new_name),
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
            class_names_to_ignore = obfuscation_info.get_class_names_to_ignore()
            renamed_methods = self.rename_method_declarations(
                obfuscation_info.get_smali_files(),
                class_names_to_ignore,
                obfuscation_info.interactive,
            )

            self.rename_method_invocations(
                obfuscation_info.get_smali_files(),
                renamed_methods,
                obfuscation_info.interactive,
            )

            out_dir = os.path.dirname(os.path.abspath(obfuscation_info.apk_path))
            apk_name = os.path.splitext(os.path.basename(obfuscation_info.apk_path))[0]
            out_file = os.path.join(out_dir, f"{apk_name}_method_mapping.json")
            self.export_mapping(self.method_mapping, out_file)

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
