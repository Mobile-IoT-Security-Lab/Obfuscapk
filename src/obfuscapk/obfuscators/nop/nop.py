#!/usr/bin/env python3

import logging
import re

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation


class Nop(obfuscator_category.ICodeObfuscator):
    inverse_conditions = {
        "eq": "ne", "ne": "eq", "lt": "ge", "ge": "lt",
        "gt": "le", "le": "gt",
    }
    conditional_branch_pattern = re.compile(
        r"^(?P<indent>[ \t]*)if-(?P<condition>eq|ne|lt|ge|gt|le)(?P<zero>z?)"
        r"\s+(?P<registers>[^\n]+?),\s*(?P<target>:[^\s#]+)"
        r"(?P<comment>[^\n]*)\n?$"
    )
    op_code_pattern = re.compile(r"\s+(?P<op_code>\S+)")
    result_producer_op_codes = {
        "filled-new-array",
        "filled-new-array/range",
    }

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        super().__init__()

    def _extract_op_code(self, line: str):
        match = self.op_code_pattern.match(line)
        if match:
            return match.group("op_code")

        return None

    def _can_insert_nop_after(self, op_code: str, next_op_code: str) -> bool:
        if next_op_code and next_op_code.startswith("move-result"):
            return not (
                op_code.startswith("invoke-")
                or op_code in self.result_producer_op_codes
            )

        return True

    def _widen_conditional_branches(self, lines):
        labels = set(re.findall(r":[^\s,#]+", "".join(lines)))
        result = []
        label_index = 0
        for line in lines:
            match = self.conditional_branch_pattern.fullmatch(line)
            if not match:
                result.append(line)
                continue
            while True:
                label = f":nop_branch_{label_index}"
                label_index += 1
                if label not in labels:
                    labels.add(label)
                    break
            inverse = self.inverse_conditions[match.group("condition")]
            result.append(
                f"{match.group('indent')}if-{inverse}{match.group('zero')} "
                f"{match.group('registers')}, {label}{match.group('comment')}\n"
                f"\tgoto/32 {match.group('target')}\n"
                f"\t{label}\n"
            )
        return result

    def _add_nops(self, lines, op_codes):
        next_ops = [None] * len(lines)
        following = None
        for index in range(len(lines) - 1, -1, -1):
            next_ops[index] = following
            op = self._extract_op_code(lines[index])
            if op and not op.startswith((".", ":", "#")):
                following = op
        result = []
        inserted_nops = False
        for index, line in enumerate(lines):
            result.append(line)
            op = self._extract_op_code(line)
            if op in op_codes and self._can_insert_nop_after(op, next_ops[index]):
                result.append("\tnop\n" * util.get_random_int(1, 5))
                inserted_nops = True
        return self._widen_conditional_branches(result) if inserted_nops else result

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info(f'Running "{self.__class__.__name__}" obfuscator')

        try:
            op_codes = set(util.get_nop_valid_op_codes())

            for smali_file in util.show_list_progress(
                obfuscation_info.get_smali_files(),
                interactive=obfuscation_info.interactive,
                description='Inserting "nop" instructions in smali files',
            ):
                self.logger.debug(
                    f'Inserting "nop" instructions in file "{smali_file}"'
                )
                with util.inplace_edit_file(smali_file) as (in_file, out_file):
                    lines = in_file.readlines()
                    out_file.writelines(self._add_nops(lines, op_codes))

        except Exception as e:
            self.logger.error(
                f'Error during execution of "{self.__class__.__name__}" obfuscator: {e}'
            )
            raise

        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)
