#!/usr/bin/env python3

import configparser
import importlib
import inspect
from pathlib import Path

from obfuscapk import obfuscator_category


class PluginInfo:
    def __init__(self, name, category, plugin_object):
        self.name = name
        self.category = category
        self.plugin_object = plugin_object


class ObfuscatorManager(object):
    def __init__(self):
        self.plugins = []
        self.categories = {
            "Trivial": obfuscator_category.ITrivialObfuscator,
            "Rename": obfuscator_category.IRenameObfuscator,
            "Encryption": obfuscator_category.IEncryptionObfuscator,
            "Code": obfuscator_category.ICodeObfuscator,
            "Resources": obfuscator_category.IResourcesObfuscator,
            "Other": obfuscator_category.IOtherObfuscator,
        }
        self._collect_plugins()

    def _collect_plugins(self):
        obfuscators_dir = Path(__file__).resolve().parent / "obfuscators"

        # For each .obfuscator file get all the metadata
        for conf_file in obfuscators_dir.rglob("*.obfuscator"):
            parser = configparser.ConfigParser()
            parser.read(conf_file)

            if not parser.has_section("Core") or not parser.has_option(
                "Core", "Module"
            ):
                continue

            name = parser.get("Core", "Name", fallback=conf_file.stem)
            module_name = parser.get("Core", "Module")

            try:
                # Import the module relaative to the .obfuscator file
                full_module_name = f"obfuscapk.obfuscators.{module_name}"
                module = importlib.import_module(full_module_name)

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if obj in self.categories.values():
                        continue

                    for cat_name, cat_interface in self.categories.items():
                        if issubclass(obj, cat_interface):
                            plugin_instance = obj()
                            self.plugins.append(
                                PluginInfo(name, cat_name, plugin_instance)
                            )
                            break

            except Exception as e:
                print(f"Error loading plugin {name} from {module_name}: {e}")

    def get_all_obfuscators(self):
        return self.plugins

    def get_obfuscators_names(self):
        return [
            ob.name
            for ob in sorted(
                self.get_all_obfuscators(), key=lambda x: (x.category, x.name)
            )
        ]
