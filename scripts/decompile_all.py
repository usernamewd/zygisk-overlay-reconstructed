#@category Reconstruction
# Ghidra headless post-script that decompiles every function in the loaded
# program to a single .c dump plus a JSON index. Used by the reconstruction
# pipeline; re-run after re-importing the binary if you re-analyse it.
#
# Usage:
#   $GHIDRA/support/analyzeHeadless <projectDir> <projectName> \
#       -import <binary>.so \
#       -postScript scripts/decompile_all.py \
#       -scriptPath scripts/

from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import os
import json

OUT_DIR = os.environ.get("DECOMP_OUT", "reverse_engineering")
try:
    os.makedirs(OUT_DIR)
except Exception:
    pass

ifc = DecompInterface()
ifc.openProgram(currentProgram)
monitor = ConsoleTaskMonitor()

fm = currentProgram.getFunctionManager()
funcs = list(fm.getFunctions(True))
print("[+] %d functions" % len(funcs))

summary = []
all_path = os.path.join(OUT_DIR, "all_functions_decompiled.c")
all_f = open(all_path, "w")

for f in funcs:
    addr = f.getEntryPoint().getOffset()
    name = f.getName()
    body = f.getBody()
    size = body.getNumAddresses() if body else 0
    sig = ""
    code = ""
    try:
        res = ifc.decompileFunction(f, 60, monitor)
        if res and res.decompileCompleted():
            dec = res.getDecompiledFunction()
            sig  = dec.getSignature() if dec else ""
            code = dec.getC()         if dec else ""
        else:
            code = "/* decompile failed: %s */\n" % (
                res.getErrorMessage() if res else "no result")
    except Exception as e:
        code = "/* exception: %s */\n" % str(e)

    all_f.write("/* ==================== 0x%x : %s (size=%d) ==================== */\n"
                % (addr, name, size))
    all_f.write(code)
    all_f.write("\n\n")

    summary.append({
        "addr": "0x%x" % addr,
        "name": name,
        "size": size,
        "sig":  sig.strip() if sig else "",
    })

all_f.close()
with open(os.path.join(OUT_DIR, "function_index.json"), "w") as s:
    json.dump(summary, s, indent=2)

print("[+] wrote %s and function_index.json" % all_path)
