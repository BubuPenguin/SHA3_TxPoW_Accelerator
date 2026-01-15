# JNI_minima Build System for SHA3 Accelerator

This directory contains the JNI build system structure compatible with Minima's native library interface.

## Structure

```
JNI_minima/
├── src/          # Java source files (optional, for header generation)
├── cc/           # C source files (sha3accelerator_jni.c)
├── lib/          # Compiled shared library output (libnative.so)
├── bin/          # Compiled Java classes (if using src/)
├── buildjni.sh   # Build script for the C JNI library
└── README.md     # This file
```

## Building

### Prerequisites

**On WSL (Cross-Compilation Host):**
- RISC-V cross-compiler: `gcc-riscv64-linux-gnu`
- Java JDK (for JNI headers - x86 version is fine)
- `JAVA_HOME` environment variable set (or JDK in standard location)

**Install RISC-V Cross-Compiler:**
```bash
sudo apt update
sudo apt install gcc-riscv64-linux-gnu
```

### Build Steps

1. **Ensure the C source file is in `cc/` directory:**
   ```bash
   ls cc/sha3accelerator_jni.c
   ```

2. **Set JAVA_HOME (if not auto-detected):**
   ```bash
   # Find your Java installation
   ls /usr/lib/jvm/
   
   # Set JAVA_HOME (adjust path as needed)
   export JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
   ```

3. **Make the build script executable:**
   ```bash
   chmod +x buildjni.sh
   ```

4. **Run the build script:**
   ```bash
   ./buildjni.sh
   ```

5. **The compiled RISC-V library will be in `lib/libnative.so`**

6. **Transfer to FPGA:**
   ```bash
   scp lib/libnative.so root@<fpga_ip>:/root/Minima/jni/lib/
   ```

7. **On FPGA, set permissions:**
   ```bash
   ssh root@<fpga_ip>
   chmod +x /root/Minima/jni/lib/libnative.so
   ```

## What Gets Built

The build script compiles `cc/sha3accelerator_jni.c` into `lib/libnative.so`, which implements Minima's JNI interface:

- **Package**: `org.minima.utils.jni.jnifunctions`
- **Functions**:
  - `sayHello()` - Helper function for library validation
  - `sumIntegers()` - Helper function for validation
  - `sayHelloToMe()` - Helper function for validation
  - `hashHeader()` - Single hash function (stub)
  - `hashHeaderWithDiff()` - Main mining function using hardware accelerator

## Differences from Original buildjni.sh

The original `buildjni.sh` was designed for C++ (`start.cpp`) and used `g++`. This updated version:

- Uses **riscv64-linux-gnu-gcc** for cross-compilation (RISC-V target)
- Compiles C code (not C++) - `sha3accelerator_jni.c` instead of `start.cpp`
- No Java header generation (header is not needed for C code)
- Creates `libnative.so` compatible with Minima's interface
- Outputs RISC-V 64-bit binary (not x86)

**Note:** The build script automatically detects the RISC-V cross-compiler and will error if it's not installed.

## Usage with Minima

The compiled `lib/libnative.so` should be:
1. Renamed to `libminima_native.so` (if Minima expects that name)
2. Placed in a directory accessible by Java's `java.library.path`
3. Or placed in system library directory (e.g., `/usr/local/lib/`)

Minima will load it via:
```java
System.loadLibrary("minima_native"); // or "native" depending on Minima config
```

## Hardware Requirements

This library requires:
- Access to `/dev/mem` (usually requires root or proper permissions)
- Hardware accelerator at base address `0xF0000000`
- Linux system with memory-mapped I/O support

