#!/usr/bin/env python3

import logging
import re
from io import StringIO
from typing import List, Set

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation


class CallIndirection(obfuscator_category.ICodeObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

        self.is_adding_methods = True

        self.registers_pattern = re.compile(r"[vp]\d{1,3}")

    def is_range(self, invoke_type: str) -> bool:
        return "range" in invoke_type

    def is_static(self, invoke_type: str) -> bool:
        return "static" in invoke_type

    def get_registers(self, invoke_pass: str) -> List[str]:
        return self.registers_pattern.findall(invoke_pass)

    def get_register_range_count(self, register_list: List[str]) -> int:
        return int(register_list[1][1:]) - int(register_list[0][1:]) + 1

    def is_void(self, invoke_return: str) -> bool:
        return invoke_return == "V"

    def is_wide(self, invoke_return: str) -> bool:
        return invoke_return == "J" or invoke_return == "D"

    def is_object(self, invoke_return: str) -> bool:
        # https://github.com/JesusFreke/smali/wiki/TypesMethodsAndFields
        return invoke_return.startswith(("L", "["))

    def is_init(self, invoke_method: str) -> bool:
        return "<init>" in invoke_method or "<clinit>" in invoke_method

    def get_wrapper_method_name(
        self, invoke_object: str, invoke_method: str, invoke_param: str
    ) -> str:
        signature = "{0}{1}{2}".format(invoke_object, invoke_method, invoke_param)
        return "m{0}".format(util.get_string_md5(signature)[:8])

    def change_method_call(
        self,
        invoke_type: str,
        invoke_pass: str,
        invoke_object: str,
        invoke_method: str,
        invoke_param: str,
        invoke_return: str,
        class_name: str,
        new_method: StringIO,
        out_file,
        generated_wrappers: Set[str],
    ) -> bool:
        """Returns True if a new wrapper method was generated, False if reused."""

        new_method_name = self.get_wrapper_method_name(
            invoke_object, invoke_method, invoke_param
        )

        is_range_invocation = self.is_range(invoke_type)
        is_static_invocation = self.is_static(invoke_type)

        register_list = self.get_registers(invoke_pass)
        if is_range_invocation:
            register_count = self.get_register_range_count(register_list)
        else:
            register_count = len(register_list)

        is_void_value = self.is_void(invoke_return)
        is_wide_value = self.is_wide(invoke_return)
        is_object_value = self.is_object(invoke_return)

        local_register_count = 1
        if is_void_value:
            local_register_count = 0
        if is_wide_value:
            local_register_count = 2

        move_result_str = "move-result v0"
        if is_void_value:
            move_result_str = ""
        if is_wide_value:
            move_result_str = "move-result-wide v0"
        if is_object_value:
            move_result_str = "move-result-object v0"

        return_str = "return v0"
        if is_void_value:
            return_str = "return-void"
        if is_wide_value:
            return_str = "return-wide v0"
        if is_object_value:
            return_str = "return-object v0"

        add_param = "" if is_static_invocation else invoke_object
        new_invoke = "invoke-static/range" if is_range_invocation else "invoke-static"

        # Insert the new method invocation in the smali file.
        out_file.write(
            "\t{invoke_type} {{{invoke_pass}}}, {class_name}->"
            "{method_name}({add_param}{invoke_param}){invoke_return}\n".format(
                invoke_type=new_invoke,
                invoke_pass=invoke_pass,
                class_name=class_name,
                method_name=new_method_name,
                add_param=add_param,
                invoke_param=invoke_param,
                invoke_return=invoke_return,
            )
        )

        wrapper_key = "{0}->{1}({2}{3}){4}".format(
            class_name, new_method_name, add_param, invoke_param, invoke_return
        )

        if wrapper_key in generated_wrappers:
            return False

        generated_wrappers.add(wrapper_key)

        # Prepare the new method(s) declaration (will be inserted later into code).
        new_method.write(
            ".method public static "
            "{method_name}({add_param}{invoke_param}){invoke_return}\n".format(
                method_name=new_method_name,
                add_param=add_param,
                invoke_param=invoke_param,
                invoke_return=invoke_return,
            )
        )
        new_method.write(
            "    .locals {local_count}\n\n".format(local_count=local_register_count)
        )
        new_method.write("    {invoke_type} {{".format(invoke_type=invoke_type))
        if is_range_invocation:
            new_method.write("p0 .. p{count}".format(count=(register_count - 1)))
        else:
            for index in range(0, register_count):
                new_method.write("p{count}".format(count=index))
                if index + 1 < register_count:
                    new_method.write(", ")
        new_method.write(
            "}}, {invoke_object}->"
            "{invoke_method}({invoke_param}){invoke_return}\n\n".format(
                invoke_object=invoke_object,
                invoke_method=invoke_method,
                invoke_param=invoke_param,
                invoke_return=invoke_return,
            )
        )
        if move_result_str:
            new_method.write(
                "    {move_result}\n\n".format(move_result=move_result_str)
            )
        new_method.write("    {return_result}\n".format(return_result=return_str))
        new_method.write(".end method\n\n")

        return True

    def update_method(
        self,
        smali_file: str,
        new_method: StringIO,
        added_methods: int,
        max_methods_to_add: int,
        generated_wrappers: Set[str],
    ) -> int:
        """Returns the number of new wrapper methods generated."""
        new_methods_count = 0

        with util.inplace_edit_file(smali_file) as (in_file, out_file):
            class_name = None
            for line in in_file:
                if not class_name:
                    class_match = util.class_pattern.search(line)
                    if class_match:
                        class_name = class_match.group("class_name")
                        out_file.write(line)
                        continue

                invoke_match = util.invoke_pattern.search(line)
                if invoke_match:
                    if (
                        not self.is_init(invoke_match.group("invoke_method"))
                        and (added_methods + new_methods_count) < max_methods_to_add
                    ):
                        # The following function will write into the file the new
                        # method invocation.
                        was_new = self.change_method_call(
                            invoke_match.group("invoke_type"),
                            invoke_match.group("invoke_pass"),
                            invoke_match.group("invoke_object"),
                            invoke_match.group("invoke_method"),
                            invoke_match.group("invoke_param"),
                            invoke_match.group("invoke_return"),
                            class_name,
                            new_method,
                            out_file,
                            generated_wrappers,
                        )
                        if was_new:
                            new_methods_count += 1
                    else:
                        out_file.write(line)
                else:
                    out_file.write(line)

        return new_methods_count

    def add_method(self, smali_file: str, new_method: StringIO):
        with util.inplace_edit_file(smali_file) as (in_file, out_file):
            for line in in_file:
                if line.startswith("# direct methods"):
                    # Add the new indirection method(s) in the direct methods section.
                    out_file.write(line)
                    out_file.write(new_method.getvalue())
                else:
                    out_file.write(line)

    def add_call_indirections(
        self, smali_files: List[str], max_methods_to_add: int, interactive: bool = False
    ):
        added_methods = 0
        generated_wrappers: Set[str] = set()

        for smali_file in util.show_list_progress(
            smali_files,
            interactive=interactive,
            description="Inserting call indirections in smali files",
        ):
            self.logger.debug(
                'Inserting call indirections in file "{0}"'.format(smali_file)
            )
            if added_methods < max_methods_to_add:
                with StringIO() as new_method:
                    new_count = self.update_method(
                        smali_file,
                        new_method,
                        added_methods,
                        max_methods_to_add,
                        generated_wrappers,
                    )
                    self.add_method(smali_file, new_method)
                    added_methods += new_count
            else:
                break

        self.logger.debug("{0} new methods were added".format(added_methods))

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        try:
            # There is a method limit for dex files.
            max_methods_to_add = obfuscation_info.get_remaining_methods_per_obfuscator()

            if obfuscation_info.is_multidex():
                for index, dex_smali_files in enumerate(
                    util.show_list_progress(
                        obfuscation_info.get_multidex_smali_files(),
                        interactive=obfuscation_info.interactive,
                        unit="dex",
                        description="Processing multidex",
                    )
                ):
                    max_methods_to_add = (
                        obfuscation_info.get_remaining_methods_per_obfuscator()[index]
                    )
                    self.add_call_indirections(
                        dex_smali_files,
                        max_methods_to_add,
                        obfuscation_info.interactive,
                    )
            else:
                self.add_call_indirections(
                    obfuscation_info.get_smali_files(),
                    max_methods_to_add,
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
