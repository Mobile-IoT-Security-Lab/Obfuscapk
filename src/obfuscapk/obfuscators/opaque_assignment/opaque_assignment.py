#!/usr/bin/env python3

import logging

from obfuscapk import obfuscator_category
from obfuscapk import util
from obfuscapk.obfuscation import Obfuscation

class OpaqueAssignment(obfuscator_category.IRenameObfuscator):
    def __init__(self):
        self.logger = logging.getLogger(
            "{0}.{1}".format(__name__, self.__class__.__name__)
        )
        super().__init__()
    
    def obfuscate(self, obfuscation_info: Obfuscation):
        self.logger.info('Running "{0}" obfuscator'.format(self.__class__.__name__))

        try:           
            for smali_file in util.show_list_progress(
                obfuscation_info.get_smali_files(),
                interactive=obfuscation_info.interactive,
                description="Inserting opaque variable assignment in smali files",
            ):
                self.logger.debug(
                    'Inserting opaque variable assignment in file "{0}"'.format(smali_file)
                )
                with util.inplace_edit_file(smali_file) as (in_file, out_file):
                    # print(f"OFUSCO QUESTO: {smali_path}, check: {"com/example/pickandeat/ManagePlateActivity.smali" not in str(smali_path)}")
                    editing_method = False
                    else_label = None
                    goto_end_condition_label = None
                    lines = []
                    local_count = 0
                    local_vars = {}
                    obfuscated = False
                    for line in in_file:
                        if (
                            line.startswith(".method ")
                            and " abstract " not in line
                            and " native " not in line
                            and " constructor " not in line
                            and " protected " not in line
                            and not editing_method
                        ):
                            # Entering method.
                            out_file.write(line)
                            editing_method = True
                        elif line.startswith(".end method") and editing_method:
                            # Exiting method.
                            for ln in lines:
                                out_file.write(ln)
                            lines = []
                            out_file.write(line)
                            editing_method = False
                            local_count = 0
                            local_vars = {}
                            obfuscated = False
                        elif editing_method:
                            local_pattern_match = util.locals_pattern.match(line)
                            if local_pattern_match:
                                local_count = int(local_pattern_match.group("local_count"))
                                # inizializzo tutti i possibili registri
                                for rx in range(local_count):
                                    local_vars[f"v{rx}"] = {"usable": True, "line": ""}                                        
                            line_number_match = util.line_number_pattern.match(line)                         
                            if line_number_match:
                                for ln in lines:
                                    out_file.write(ln)
                                out_file.write(line)
                                lines = []
                                continue
                            const_var_pattern_match = util.instruction_register_pattern.match(line)
                            if const_var_pattern_match:
                                local_vars[const_var_pattern_match.group("register")] = {"usable": False, "line": line}
                            else:
                                for key in local_vars.keys():
                                    # il registro deve essere nella linea, non deve essere una iput e deve essere usable
                                    if key in line and not util.iput_pattern.match(line):
                                        local_vars[key] = {"usable": False, "line": ""}
                            local_var_match = util.local_var_pattern.match(line)
                            if local_var_match:
                            #     # rimuovo il registro che viene utilizzato per memorizzare dati importanti, non lo considero per l'if dell'ofuscatore
                                local_var = local_var_match.group(1)
                                local_vars[local_var] = {"usable": False, "line": ""}
                            #     if local_var in local_vars:
                            #         # potrei entrarci piu' volte con lo stesso registro perche' puo' venire riutilizzato all'interno del metodo
                            #         local_vars.remove(local_var)
                            var_assignment_match = util.iput_pattern.match(line)
                            if var_assignment_match and not obfuscated:
                                local_var = False
                                for l in lines:
                                    if l.strip().startswith("."):
                                        local_var = True
                                if local_var: # se c'e' una variabile .local nella linea dell'iput, non ofuschiamo
                                    lines.append(line)
                                    continue

                                usable_regs = []
                                for key in local_vars.keys():
                                    if local_vars[key]["usable"]:
                                        usable_regs.append(key)
                                if len(usable_regs) < 2:
                                    # non ci sono almeno 2 registri liberi, non posso ofuscare
                                    lines.append(line)
                                    continue
                                
                                # ci sono almeno 2 registri liberi, prendo i primi due
                                v0_label = usable_regs[0]
                                v1_label = usable_regs[1]

                                v0, v1 = (
                                    util.get_random_int(1, 32),
                                    util.get_random_int(1, 32),
                                )
                                else_label = util.get_random_string(16)
                                goto_end_condition_label = util.get_random_string(16)
                                opaque_lines = []
                                opaque_lines.append("\n\tconst {0}, {1}\n".format(v0_label, v0))
                                opaque_lines.append("\tconst {0}, {1}\n".format(v1_label, v1))
                                opaque_lines.append("\tadd-int {0}, {1}, {2}\n".format(v0_label, v0_label, v1_label))
                                opaque_lines.append("\trem-int {0}, {1}, {2}\n".format(v0_label, v0_label, v1_label))
                                opaque_lines.append("\tif-lez {0}, :{1}\n".format(v0_label, else_label))
                                # ripristinare evenutali valori dei registri
                                for usable_reg in usable_regs:
                                    reg_line = local_vars[usable_reg]["line"]
                                    if reg_line not in lines:
                                        lines.append(local_vars[usable_reg]["line"])
                                # scriviamo resto del codice
                                tmp_lines = []
                                for l in lines:
                                    if l.strip().startswith("."):
                                        tmp_lines.append(l)
                                    else:
                                        opaque_lines.append(l)
                                lines = tmp_lines + opaque_lines
                                lines.append(line) # istruzione iput   
                                lines.append("\tgoto/32 :{0}\n".format(goto_end_condition_label))
                                lines.append("\t:{0}\n".format(else_label))
                                lines.append("\t:{0}\n".format(goto_end_condition_label))
                                else_label = None
                                goto_end_condition_label = None
                                obfuscated = True
                            else:
                                lines.append(line)
                        else:
                            out_file.write(line)
        except Exception as e:
            self.logger.error(
                'Error during execution of "{0}" obfuscator: {1}'.format(
                    self.__class__.__name__, e
                )
            )
            raise

        finally:
            obfuscation_info.used_obfuscators.append(self.__class__.__name__)