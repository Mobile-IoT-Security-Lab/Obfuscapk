# Opaque Assignment

## Description

Opaque-assignments is an obfuscator born from the idea of obfuscating portions of code, in particular assignments. This choice stems from the fact that an assignment — unlike other code — when “surrounded” by an arbitrary evaluation of a condition does not create problems/errors because the variable’s scope remains unchanged.

This makes the job of reversing more difficult: an analyst trying to understand why certain `if` statements were inserted will be misled, slowed down, and forced to spend extra time reversing an APK.

The obfuscator is based on the concept of an “opaque predicate”. https://en.wikipedia.org/wiki/Opaque_predicate

## Implementation details

The plugin scans all Smali files of the application and analyzes only the methods that are not abstract, native, constructors, or protected. For each method we keep track of the available local registers by intercepting the line `.locals X` inside the smali file, where `X` represents the number of registers.

If the available registers are fewer than two we cannot apply the obfuscation technique because there are not enough free registers to use in the `if` condition.

The plugin therefore scans the method line by line and marks as unusable any register that is used by an instruction (via pattern matching). This is because we do not want to overwrite any existing values in registers. Initially we thought of saving the register values and, after the inserted fake condition, restoring the values back into the registers. However, this approach caused several `VerifyError` problems when installing the app on the device/emulator: the error indicated that the Android JVM verifier was rejecting the code because the plugin ad inserted a branching instruction with incompatible types (for example, comparing an `Undefined` type with a `ByteConstant`).

Finally, when the plugin encounters any `iput`, `iput-object`, `iput-boolean`, etc. (field assignment), the obfuscator selects two still-available registers and inserts the following smali instructions:
- Two random constants into the selected registers
- An addition operation between these values
- A modulo (remainder) operation
- A conditional check (`if-ltz`) that creates a fake branch because the operation performed will always return a result > 0

The inserted code follows this pattern:
```
const vX, [random_number_1]     # Insert a 32-bit integer constant into register vX
const vY, [random_number_2]     # Insert a 32-bit integer constant into register vY
add-int vX, vX, vY              # Compute vX + vY and store result in vX
rem-int vX, vX, vY              # Compute vX % vY and store result in vX
if-ltz vX, :label_else          # Jump to :label_else if vX < 0
[original iput instruction]
:label_else
```

[This](https://sallam.gitbook.io/sec-88/android-appsec/smali/smali-cheat-sheet) resource was particularly useful to get more information about smali code.

The plugin is applied only once per method, using an `obfuscated` flag that indicates whether an assignment to obfuscate has already been found. Additionally, the plugin avoids inserting obfuscation in the presence of local variable metadata (`.local`) or try-catch blocks to prevent verification errors.

