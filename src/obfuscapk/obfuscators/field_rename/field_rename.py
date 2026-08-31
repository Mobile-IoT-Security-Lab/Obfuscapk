#!/usr/bin/env python3

import logging
from typing import List, Optional, Set, Tuple

from obfuscapk import obfuscator_category, util
from obfuscapk.obfuscation import Obfuscation


class FieldRename(obfuscator_category.IRenameObfuscator):
    field_reflection_methods = {"getField", "getDeclaredField"}

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
        self.class_interfaces = {}
        self.native_classes = set()
        self.protected_field_names: Set[str] = set()
        self.protected_fields: Set[Tuple[str, str]] = set()
        self.protected_field_classes: Set[str] = set()
        self.has_unknown_field_reflection = False

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
                        # Looks for the class name in the .class declaration
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")
                    elif class_name:
                        # Looks for the superclass name in the .super declaration
                        super_match = util.super_class_pattern.search(line)
                        if super_match:
                            self.class_superclasses[class_name] = super_match.group(
                                "class_name"
                            )

                        interface_match = util.implements_pattern.search(line)
                        if interface_match:
                            self.class_interfaces.setdefault(class_name, set()).add(
                                interface_match.group("class_name")
                            )

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

    def unescape_smali_string(self, value: str) -> str:
        escapes = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r"}
        result = []
        index = 0
        while index < len(value):
            if value[index] != "\\" or index + 1 == len(value):
                result.append(value[index])
                index += 1
                continue

            escaped = value[index + 1]
            if escaped == "u" and index + 5 < len(value):
                try:
                    result.append(chr(int(value[index + 2 : index + 6], 16)))
                    index += 6
                    continue
                except ValueError:
                    pass
            result.append(escapes.get(escaped, escaped))
            index += 2
        return "".join(result)

    def protect_and_clear(self, register_values, class_register_values):
        self.protected_field_names.update(register_values.values())
        register_values.clear()
        class_register_values.clear()

    def protect_field(
        self,
        class_name: str,
        field_name: Optional[str],
        include_inherited: bool,
    ):
        pending_classes = [class_name]
        visited_classes = set()
        while pending_classes:
            current_class = pending_classes.pop()
            if current_class in visited_classes:
                continue

            visited_classes.add(current_class)
            if field_name is None:
                self.protected_field_classes.add(current_class)
            else:
                self.protected_fields.add((current_class, field_name))

            # Include inherited classes/interfaces
            if include_inherited:
                superclass = self.class_superclasses.get(current_class)
                if superclass:
                    pending_classes.append(superclass)
                pending_classes.extend(self.class_interfaces.get(current_class, ()))

    def collect_protected_field_names(self, smali_files: List[str]):
        """Find field names passed to reflection within simple basic blocks"""
        self.protected_field_names.clear()
        self.protected_fields.clear()
        self.protected_field_classes.clear()
        self.has_unknown_field_reflection = False
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                register_values = {}
                class_register_values = {}
                in_method = False
                for line in current_file:
                    stripped_line = line.strip()
                    if stripped_line.startswith(".method "):
                        register_values.clear()
                        class_register_values.clear()
                        in_method = True
                        continue
                    if stripped_line == ".end method":
                        register_values.clear()
                        class_register_values.clear()
                        in_method = False
                        continue
                    # Ignore lines outside of methods
                    if not in_method:
                        continue

                    # A label starts a new basic block
                    if stripped_line.startswith(":"):
                        self.protect_and_clear(
                            register_values, class_register_values
                        )
                        continue

                    # Record string constants
                    string_match = util.const_string_pattern.search(line)
                    if string_match:
                        register = string_match.group("register")
                        register_values[register] = (
                            self.unescape_smali_string(string_match.group("string"))
                        )
                        class_register_values.pop(register, None)
                        continue


                    class_match = util.const_class_pattern.search(line)
                    if class_match:
                        register = class_match.group("register")
                        class_register_values[register] = class_match.group(
                            "class_name"
                        )
                        register_values.pop(register, None)
                        continue

                    # Track move instructions
                    move_match = util.smali_move_pattern.match(line)
                    if move_match:
                        destination = move_match.group("destination")
                        source = move_match.group("source")
                        for values in (register_values, class_register_values):
                            if source in values:
                                values[destination] = values[source]
                            else:
                                values.pop(destination, None)
                        continue

                    invoke_match = util.invoke_pattern.search(line)
                    if invoke_match:
                        # Check if the invoke is a field reflection call
                        is_field_reflection = (
                            invoke_match.group("invoke_object")
                            == "Ljava/lang/Class;"
                            and invoke_match.group("invoke_method")
                            in self.field_reflection_methods
                            and invoke_match.group("invoke_param")
                            == "Ljava/lang/String;"
                        )
                        registers = util.get_invoke_registers(
                            invoke_match.group("invoke_pass")
                        )
                        # Get register values for field reflection call
                        if is_field_reflection and len(registers) >= 2:
                            field_name = register_values.get(registers[-1])
                            target_class = class_register_values.get(registers[0])
                            if field_name is not None and target_class:
                                self.protect_field(
                                    target_class,
                                    field_name,
                                    invoke_match.group("invoke_method") == "getField",
                                )
                            elif field_name is not None:
                                self.protected_field_names.add(field_name)
                            elif target_class:
                                self.protect_field(
                                    target_class,
                                    None,
                                    invoke_match.group("invoke_method") == "getField",
                                )
                            else:
                                self.has_unknown_field_reflection = True
                        elif is_field_reflection:
                            self.has_unknown_field_reflection = True
                        continue

                    instruction_match = util.smali_instruction_pattern.match(line)
                    if not instruction_match:
                        continue
                    opcode = instruction_match.group("opcode")

                    if opcode.startswith(
                        ("if-", "goto", "packed-switch", "sparse-switch")
                    ):
                        self.protect_and_clear(
                            register_values, class_register_values
                        )
                        continue
                    if opcode.startswith(("return", "throw")):
                        register_values.clear()
                        class_register_values.clear()
                        continue

                    destination = instruction_match.group("register")
                    reads_first_register = opcode.startswith(
                        (
                            "invoke-",
                            "iput",
                            "sput",
                            "aput",
                            "monitor-",
                            "check-cast",
                            "fill-array-data",
                            "filled-new-array",
                        )
                    )
                    if destination and not reads_first_register:
                        register_values.pop(destination, None)
                        class_register_values.pop(destination, None)
                        if "wide" in opcode:
                            next_register = "{0}{1}".format(
                                destination[0], int(destination[1:]) + 1
                            )
                            register_values.pop(next_register, None)
                            class_register_values.pop(next_register, None)

    def rename_field_declarations(
        self, smali_files: List[str], interactive: bool = False
    ) -> Set[str]:
        renamed_fields: Set[str] = set()

        if self.has_unknown_field_reflection:
            self.logger.warning(
                "Skipping field renaming because neither the reflective field "
                "name nor its target class could be resolved"
            )
            return renamed_fields

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
                            # Skip enum declarations
                            skip_remaining_lines = True
                            out_file.write(line)
                            continue
                        elif class_match:
                            # Get the class name
                            class_name = class_match.group("class_name")

                    # Get the field name
                    field_match = util.field_pattern.search(line)

                    # Ignore fields from ignored packages or native classes
                    if (class_name and class_name.startswith(
                            tuple(self.ignore_package_names)
                        )
                    ) or class_name in self.native_classes:
                        ignore = True

                    if field_match:
                        old_name = field_match.group("field_name")
                        field_type = field_match.group("field_type")

                        if (
                            not ignore
                            and "$" not in old_name  # Ignore compiler-generated fields
                            and old_name not in self.protected_field_names  # Ignore protected fields
                            and (class_name, old_name) not in self.protected_fields
                            and class_name not in self.protected_field_classes
                        ):
                            mapping_key = self.get_field_key(
                                class_name, old_name, field_type
                            )

                            # Ignore fields that are already mapped
                            if mapping_key not in self.field_mapping:
                                self.field_mapping[mapping_key] = "f{0}".format(
                                    self.field_counter
                                )
                                self.field_counter += 1

                            new_name = self.field_mapping[mapping_key]

                            # Rename the field
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

            self.collect_superclasses(all_smali_files)
            self.collect_protected_field_names(all_smali_files)
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
