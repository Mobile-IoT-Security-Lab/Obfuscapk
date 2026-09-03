#!/usr/bin/env python3

import json
import logging
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from obfuscapk import obfuscator_category, util
from obfuscapk.obfuscation import Obfuscation


class _ClassInfo:
    def __init__(self, selected: bool):
        self.selected = selected
        self.superclass: Optional[str] = None
        self.interfaces: Set[str] = set()
        self.methods: Dict[str, str] = {}
        self.related_classes: Set[str] = set()
        self.is_enum = False
        self.has_native_methods = False


class MethodRename(obfuscator_category.IRenameObfuscator):
    reflection_methods = {"getMethod", "getDeclaredMethod"}
    reserved_method_names = {
        "<init>",
        "<clinit>",
        "clone",
        "equals",
        "finalize",
        "hashCode",
        "main",
        "readObject",
        "readObjectNoData",
        "readResolve",
        "toString",
        "valueOf",
        "values",
        "writeObject",
        "writeReplace",
    }
    xml_on_click_pattern = re.compile(r"(?:android:)?onClick\s*=\s*[\"']([^\"']+)")

    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

        self.ignore_package_names = []
        self.method_mapping: Dict[str, str] = {}
        self.method_counter = 0

        self.classes: Dict[str, _ClassInfo] = {}
        self.reserved_signatures: Set[str] = set()
        self.reflected_method_keys: Set[str] = set()
        self.has_unknown_method_reflection = False
        self.xml_callback_mapping: Dict[str, str] = {}

    def get_method_signature(
        self, method_name: str, params: str, returns: str
    ) -> str:
        return "{0}({1}){2}".format(method_name, params, returns)

    def get_method_key(
        self, class_name: str, method_name: str, params: str, returns: str
    ) -> str:
        return "{0}->{1}".format(
            class_name, self.get_method_signature(method_name, params, returns)
        )

    def get_method_declaration(self, method_key: str) -> str:
        class_name, signature = method_key.split("->", 1)
        return self.classes[class_name].methods[signature]

    def collect_method_data(
        self,
        smali_files: List[str],
        all_smali_files:List[str],
        class_names_to_ignore: Optional[Set[str]] = None,
    ):
        """
        Collect declarations and class relationships before modifying files
        """
        all_smali_files = all_smali_files
        selected_files = set(smali_files)

        self.method_mapping.clear()
        self.method_counter = 0
        self.classes.clear()
        class_names_to_ignore = class_names_to_ignore or set()
        self.reserved_signatures.clear()
        self.reflected_method_keys.clear()
        self.has_unknown_method_reflection = False
        self.xml_callback_mapping.clear()

        # collect method data from each smali file
        for smali_file in all_smali_files:
            with open(smali_file, "r", encoding="utf-8") as file:
                class_name = None
                class_info = None

                for line in file:
                    # get basic class info
                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")
                            ignored = (
                                smali_file not in selected_files
                                or class_name in class_names_to_ignore
                                or class_name.startswith(
                                    tuple(self.ignore_package_names)
                                )
                            )
                            class_info = _ClassInfo(not ignored)
                            class_info.is_enum = " enum " in line
                            class_info.has_native_methods = (
                                "JNI;" in class_name or "/Native" in class_name
                            )
                            self.classes[class_name] = class_info
                        continue

                    # get superclass
                    super_match = util.super_class_pattern.search(line)
                    if super_match:
                        class_info.superclass = super_match.group("class_name")
                        continue

                    # get interfaces
                    interface_match = util.implements_pattern.search(line)
                    if interface_match:
                        class_info.interfaces.add(
                            interface_match.group("class_name")
                        )
                        continue

                    # get methods infos
                    method_match = util.method_pattern.search(line)
                    if method_match:
                        signature = self.get_method_signature(
                            method_match.group("method_name"),
                            method_match.group("method_param"),
                            method_match.group("method_return"),
                        )
                        class_info.methods[signature] = line
                        self.reserved_signatures.add(signature)
                        if " native " in line:
                            class_info.has_native_methods = True

        self.collect_related_classes()

    def collect_related_classes(self):
        # Create a graph of related classes
        relations = {class_name: set() for class_name in self.classes}
        for class_name, class_info in self.classes.items():
            for interface in class_info.interfaces:
                if interface in self.classes:
                    relations[class_name].add(interface)
                    relations[interface].add(class_name)
            if class_info.superclass in self.classes:
                relations[class_name].add(class_info.superclass)
                relations[class_info.superclass].add(class_name)

        # Traverse the graph to collect related classes
        remaining_classes = set(self.classes)
        while remaining_classes:
            current_class = remaining_classes.pop()
            related_classes = {current_class}
            pending_classes = [current_class]

            while pending_classes:
                for related_class in relations[pending_classes.pop()]:
                    if related_class not in related_classes:
                        related_classes.add(related_class)
                        pending_classes.append(related_class)

            for class_name in related_classes:
                self.classes[class_name].related_classes = related_classes
            remaining_classes.difference_update(related_classes)

    def protect_reflected_method(
        self, class_name: str, method_name: str, params: str
    ):
        """Resolve a reflection lookup to the full declared Smali method key."""
        pending_classes = [class_name]
        visited_classes = set()
        signature_prefix = "{0}({1})".format(method_name, params)

        while pending_classes:
            current_class = pending_classes.pop()
            if current_class in visited_classes:
                continue
            visited_classes.add(current_class)

            class_info = self.classes.get(current_class)
            if not class_info:
                continue
            for signature in class_info.methods:
                if signature.startswith(signature_prefix):
                    self.reflected_method_keys.add(
                        "{0}->{1}".format(current_class, signature)
                    )

            if class_info.superclass:
                pending_classes.append(class_info.superclass)
            pending_classes.extend(class_info.interfaces)

    def collect_reflected_methods(self, smali_files: List[str]):
        """Protect exact Class.getMethod/getDeclaredMethod targets."""
        for smali_file in smali_files:
            with open(smali_file, "r", encoding="utf-8") as current_file:
                register_values = {}
                in_method = False

                def get_value(register, value_type):
                    value = register_values.get(register)
                    if value and value[0] == value_type:
                        return value[1]
                    return None

                for line in current_file:
                    stripped_line = line.strip()
                    if stripped_line.startswith(".method "):
                        register_values.clear()
                        in_method = True
                        continue
                    if stripped_line.startswith(".end method"):
                        register_values.clear()
                        in_method = False
                        continue
                    if not in_method:
                        continue
                    if stripped_line.startswith(":"):
                        register_values.clear()
                        continue

                    # Look for string constants (method name)
                    string_match = util.const_string_pattern.search(line)
                    if string_match:
                        register = string_match.group("register")
                        register_values[register] = (
                            "string",
                            util.unescape_smali_string(string_match.group("string")),
                        )
                        continue

                    # Look for class name string constants
                    class_match = util.const_class_pattern.search(line)
                    if class_match:
                        register = class_match.group("register")
                        register_values[register] = (
                            "class",
                            class_match.group("class_name"),
                        )
                        continue

                    # Look for integer constants
                    int_match = util.const_int_pattern.search(line)
                    if int_match:
                        register = int_match.group("register")
                        register_values[register] = (
                            "int",
                            int(int_match.group("value"), 0),
                        )
                        continue

                    # Look for move operation and update register values accordingly
                    move_match = util.smali_move_pattern.match(line)
                    if move_match:
                        destination = move_match.group("destination")
                        source = move_match.group("source")
                        if source in register_values:
                            register_values[destination] = register_values[source]
                        else:
                            register_values.pop(destination, None)
                        continue

                    # Look for new array (method paramether array)
                    new_array_match = util.new_class_array_pattern.search(line)
                    if new_array_match:
                        array_register = new_array_match.group("array")
                        array_size = get_value(new_array_match.group("size"), "int")
                        if array_size is not None and array_size >= 0:
                            register_values[array_register] = (
                                "class_array",
                                [None] * array_size,
                            )
                        else:
                            register_values.pop(array_register, None)
                        continue

                    # Look for array put operation on the array (with the method paramethers)
                    array_put_match = util.array_put_object_pattern.search(line)
                    if array_put_match:
                        array_register = array_put_match.group("array")
                        # get the array of params
                        class_array = get_value(array_register, "class_array")
                        # get the value to put in the array
                        class_value = get_value(
                            array_put_match.group("value"), "class"
                        )
                        index = get_value(array_put_match.group("index"), "int")
                        if (
                            class_array is not None
                            and class_value is not None
                            and index is not None
                            and 0 <= index < len(class_array)
                        ):
                            class_array[index] = class_value
                        else:
                            register_values.pop(array_register, None)
                        continue

                    # Look for invoke operation and update register values accordingly
                    invoke_match = util.invoke_pattern.search(line)
                    if invoke_match:
                        is_reflection = (
                            invoke_match.group("invoke_object")
                            == "Ljava/lang/Class;"
                            and invoke_match.group("invoke_method")
                            in self.reflection_methods
                        )
                        if is_reflection:
                            registers = util.get_invoke_registers(
                                invoke_match.group("invoke_pass")
                            )
                            if len(registers) < 3:
                                self.has_unknown_method_reflection = True
                                continue

                            target_class = get_value(registers[0], "class")
                            method_name = get_value(registers[1], "string")
                            class_array = get_value(registers[2], "class_array")
                            if (
                                target_class is None
                                or method_name is None
                                or class_array is None
                                or any(value is None for value in class_array)
                            ):
                                self.has_unknown_method_reflection = True
                            else:
                                params = "".join(class_array)
                                self.protect_reflected_method(
                                    target_class, method_name, params
                                )
                        continue

                    instruction_match = util.smali_instruction_pattern.match(line)
                    if not instruction_match:
                        continue

                    opcode = instruction_match.group("opcode")
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
                    destination = instruction_match.group("register")
                    if destination and not reads_first_register:
                        register_values.pop(destination, None)

    def get_xml_files(self, resource_directory: str):
        if not resource_directory or not os.path.isdir(resource_directory):
            return

        for root, _, files in os.walk(resource_directory):
            for file_name in files:
                if file_name.endswith(".xml"):
                    yield os.path.join(root, file_name)

    def collect_xml_callback_names(self, resource_directory: str):
        for xml_file in self.get_xml_files(resource_directory):
            with open(xml_file, "r", encoding="utf-8") as current_file:
                content = current_file.read()
            for method_name in self.xml_on_click_pattern.findall(content):
                self.xml_callback_mapping[method_name] = ""

    def rewrite_xml_callback_names(self, resource_directory: str):
        def replace_callback(match):
            new_name = self.xml_callback_mapping.get(match.group(1))
            if not new_name:
                return match.group(0)
            return match.group(0).replace(match.group(1), new_name, 1)

        for xml_file in self.get_xml_files(resource_directory):
            with open(xml_file, "r", encoding="utf-8") as current_file:
                content = current_file.read()
            new_content = self.xml_on_click_pattern.sub(replace_callback, content)
            if new_content != content:
                with open(xml_file, "w", encoding="utf-8") as current_file:
                    current_file.write(new_content)

    def get_virtual_method_family(self, method_key: str) -> Set[str]:
        class_name, signature = method_key.split("->", 1)
        method_family = set()

        for related_class in self.classes[class_name].related_classes:
            declaration = self.classes[related_class].methods.get(signature)
            if (
                declaration
                and " private " not in declaration
                and " static " not in declaration
            ):
                method_family.add("{0}->{1}".format(related_class, signature))

        return method_family

    def has_external_hierarchy(self, class_names: Set[str]) -> bool:
        for class_name in class_names:
            class_info = self.classes[class_name]
            if (
                class_info.superclass
                and class_info.superclass != "Ljava/lang/Object;"
                and class_info.superclass not in self.classes
            ):
                return True
            if any(
                interface not in self.classes
                for interface in class_info.interfaces
            ):
                return True
        return False

    def has_external_interface(self, class_names: Set[str]) -> bool:
        return any(
            interface not in self.classes
            for class_name in class_names
            for interface in self.classes[class_name].interfaces
        )

    def is_xml_callback_method(self, method_key: str) -> bool:
        signature = method_key.split("->", 1)[1]
        method_name = signature.split("(", 1)[0]
        declaration = self.get_method_declaration(method_key)
        return (
            method_name in self.xml_callback_mapping
            and signature == "{0}(Landroid/view/View;)V".format(method_name)
            and " public " in declaration
            and " static " not in declaration
        )

    def prepare_xml_callback_renaming(self):
        for method_name in list(self.xml_callback_mapping):
            signature = "{0}(Landroid/view/View;)V".format(method_name)
            callback_methods = [
                "{0}->{1}".format(class_name, signature)
                for class_name, class_info in self.classes.items()
                if signature in class_info.methods
            ]
            if not callback_methods or not all(
                self.is_xml_callback_method(method_key)
                and self.can_rename_method(method_key, allow_xml_callback=True)[0]
                for method_key in callback_methods
            ):
                del self.xml_callback_mapping[method_name]

    def can_rename_method(
        self, method_key: str, allow_xml_callback: bool = False
    ) -> Tuple[bool, Set[str]]:
        class_name = method_key.split("->", 1)[0]
        class_info = self.classes[class_name]
        declaration = self.get_method_declaration(method_key)
        method_name = method_key.split("->", 1)[1].split("(", 1)[0]
        method_family = {method_key}

        if (
            not class_info.selected
            or class_info.is_enum
            or class_info.has_native_methods
            or method_name in self.reserved_method_names
            or method_key in self.reflected_method_keys
            or " native " in declaration
            or " access$" in declaration
            or " synthetic " in declaration
            or " bridge " in declaration
            or self.has_unknown_method_reflection
        ):
            return False, method_family

        is_direct = " private " in declaration or " static " in declaration
        if is_direct:
            return True, method_family

        method_family = self.get_virtual_method_family(method_key)
        related_classes = class_info.related_classes
        can_rename_xml_callback = (
            allow_xml_callback
            and self.is_xml_callback_method(method_key)
            and not self.has_external_interface(related_classes)
        )
        if self.has_external_hierarchy(related_classes) and not can_rename_xml_callback:
            return False, method_family

        for family_key in method_family:
            family_class = family_key.split("->", 1)[0]
            family_info = self.classes[family_class]
            family_declaration = self.get_method_declaration(family_key)
            if (
                not family_info.selected
                or family_info.is_enum
                or family_info.has_native_methods
                or " access$" in family_declaration
                or " synthetic " in family_declaration
                or " bridge " in family_declaration
            ):
                return False, method_family

        return True, method_family

    def get_new_method_name(self, method_key: str) -> str:
        signature = method_key.split("->", 1)[1]
        params_and_return = signature[signature.index("(") :]

        while True:
            new_name = "m{0}".format(self.method_counter)
            self.method_counter += 1
            new_signature = "{0}{1}".format(new_name, params_and_return)
            if new_signature not in self.reserved_signatures:
                self.reserved_signatures.add(new_signature)
                return new_name

    def rename_method_declarations(
        self,
        smali_files: List[str],
        class_names_to_ignore: Set[str],
        interactive: bool = False,
    ) -> Set[str]:
        renamed_methods: Set[str] = set()

        if not self.classes:
            self.collect_method_data(smali_files, smali_files, class_names_to_ignore)
            self.collect_reflected_methods(smali_files)

        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming method declarations",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                class_name = None

                for line in in_file:
                    if not class_name:
                        class_match = util.class_pattern.search(line)
                        if class_match:
                            class_name = class_match.group("class_name")
                        out_file.write(line)
                        continue

                    method_match = util.method_pattern.search(line)
                    if not method_match:
                        out_file.write(line)
                        continue

                    old_name = method_match.group("method_name")
                    method_key = self.get_method_key(
                        class_name,
                        old_name,
                        method_match.group("method_param"),
                        method_match.group("method_return"),
                    )
                    is_xml_callback = self.is_xml_callback_method(method_key)
                    can_rename, method_family = self.can_rename_method(
                        method_key, allow_xml_callback=is_xml_callback
                    )
                    if not can_rename:
                        out_file.write(line)
                        continue

                    if method_key not in self.method_mapping:
                        new_name = (
                            self.xml_callback_mapping.get(old_name)
                            if is_xml_callback
                            else None
                        )
                        if not new_name:
                            new_name = self.get_new_method_name(method_key)
                            if is_xml_callback:
                                self.xml_callback_mapping[old_name] = new_name
                        for family_key in method_family:
                            self.method_mapping[family_key] = new_name

                    new_name = self.method_mapping[method_key]
                    out_file.write(
                        line.replace(
                            "{0}(".format(old_name),
                            "{0}(".format(new_name),
                        )
                    )
                    renamed_methods.add(method_key)

        return renamed_methods

    def get_method_mapping_key(
        self, owner: str, method_name: str, params: str, returns: str
    ) -> str:
        pending_classes = [owner]
        visited_classes = set()

        while pending_classes:
            class_name = pending_classes.pop()
            if class_name in visited_classes:
                continue
            visited_classes.add(class_name)

            method_key = self.get_method_key(class_name, method_name, params, returns)
            if method_key in self.method_mapping:
                return method_key

            class_info = self.classes.get(class_name)
            if class_info:
                if class_info.superclass:
                    pending_classes.append(class_info.superclass)
                pending_classes.extend(class_info.interfaces)

        return ""

    def rename_method_invocations(
        self,
        smali_files: List[str],
        methods_to_rename: Set[str],
        interactive: bool = False,
    ):
        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Renaming method references",
        ):
            with util.inplace_edit_file(smali_file) as (in_file, out_file):
                for line in in_file:

                    def replace_reference(match):
                        mapping_key = self.get_method_mapping_key(
                            match.group("method_object"),
                            match.group("method_name"),
                            match.group("method_param"),
                            match.group("method_return"),
                        )
                        if not mapping_key or mapping_key not in methods_to_rename:
                            return match.group(0)

                        return "{0}->{1}({2}){3}".format(
                            match.group("method_object"),
                            self.method_mapping[mapping_key],
                            match.group("method_param"),
                            match.group("method_return"),
                        )

                    out_file.write(
                        util.method_reference_pattern.sub(replace_reference, line)
                    )

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        self.ignore_package_names = obfuscation_info.get_ignore_package_names()

        try:
            smali_files = obfuscation_info.get_smali_files()
            all_smali_files = obfuscation_info.get_all_smali_files()
            class_names_to_ignore = obfuscation_info.get_class_names_to_ignore()
            resource_directory = obfuscation_info.get_resource_directory()

            self.collect_method_data(
                smali_files, all_smali_files, class_names_to_ignore
            )
            self.collect_reflected_methods(all_smali_files)
            self.collect_xml_callback_names(resource_directory)
            self.prepare_xml_callback_renaming()

            if self.has_unknown_method_reflection:
                self.logger.warning(
                    "Skipping method renaming because a reflective method name "
                    "could not be resolved"
                )

            renamed_methods = self.rename_method_declarations(
                smali_files,
                class_names_to_ignore,
                obfuscation_info.interactive,
            )
            self.rename_method_invocations(
                all_smali_files,
                renamed_methods,
                obfuscation_info.interactive,
            )
            self.rewrite_xml_callback_names(resource_directory)

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
