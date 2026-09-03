#!/usr/bin/env python3

import logging
import re

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation


class Nop(obfuscator_category.ICodeObfuscator):
    op_code_pattern = re.compile(r"\s+(?P<op_code>\S+)")
    result_producer_op_codes = {
        "filled-new-array",
        "filled-new-array/range",
    }

    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()

    def _extract_op_code(self, line: str):
        match = self.op_code_pattern.match(line)
        if match:
            return match.group("op_code")

        return None

    def _get_next_op_code(self, lines, start_index: int):
        for line in lines[start_index:]:
            op_code = self._extract_op_code(line)
            if op_code and not op_code.startswith((".", ":", "#")):
                return op_code

        return None

    def _can_insert_nop_after(self, op_code: str, next_op_code: str) -> bool:
        if next_op_code and next_op_code.startswith("move-result"):
            return not (
                op_code.startswith("invoke-")
                or op_code in self.result_producer_op_codes
            )

        return True

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        try:
            op_codes = util.get_nop_valid_op_codes()

            for smali_file in util.show_list_progress(
                obfuscation_info.get_smali_files(),
                interactive=obfuscation_info.interactive,
                description='Inserting "nop" instructions in smali files',
            ):
                self.logger.debug(
                    'Inserting "nop" instructions in file "{0}"'.format(smali_file)
                )
                with util.inplace_edit_file(smali_file) as (in_file, out_file):
                    lines = in_file.readlines()
                    for line_number, line in enumerate(lines):
                        # Print original instruction.
                        out_file.write(line)

                        # Check if this line contains an op code at the beginning
                        # of the string.
                        op_code = self._extract_op_code(line)
                        if op_code:
                            # If this is a valid op code, insert some nop instructions
                            # after it.
                            next_op_code = self._get_next_op_code(
                                lines, line_number + 1
                            )
                            if op_code in op_codes and self._can_insert_nop_after(
                                op_code, next_op_code
                            ):
                                nop_count = util.get_random_int(1, 5)
                                out_file.write("\tnop\n" * nop_count)

        except Exception as e:
            self.logger.error(
                'Error during execution of "{0}" obfuscator: {1}'.format(
                    self.__class__.__name__, e
                )
            )
            raise

        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)
