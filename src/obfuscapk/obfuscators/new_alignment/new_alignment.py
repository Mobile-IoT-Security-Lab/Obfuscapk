#!/usr/bin/env python3

import logging

from obfuscapk import obfuscator_category
from obfuscapk.obfuscation import Obfuscation


class NewAlignment(obfuscator_category.ITrivialObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        super().__init__()

    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info(f'Running "{self.__class__.__name__}" obfuscator')

        try:
            obfuscation_info.align_obfuscated_apk()
        except Exception as e:
            self.logger.error(
                f'Error during execution of "{self.__class__.__name__}" obfuscator: {e}'
            )
            raise

        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)
