#!/bin/sh

# Build script for Minima JNI with SHA3 Accelerator (RISC-V Cross-Compilation)
# This builds the C-based JNI library for Minima on RISC-V architecture
# 
# Prerequisites:
#   - RISC-V cross-compiler: sudo apt install gcc-riscv64-linux-gnu
#   - JAVA_HOME set to your WSL Java installation (for JNI headers)
#
# Usage:
#   export JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"  # Adjust path as needed
#   ./buildjni.sh

# Check for JAVA_HOME
if [ -z "$JAVA_HOME" ]; then
    # Try to find JAVA_HOME automatically (for WSL x86 Java installation)
    if [ -d "/usr/lib/jvm/default-java" ]; then
        export JAVA_HOME="/usr/lib/jvm/default-java"
    elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then
        export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
    elif [ -d "/usr/lib/jvm/java-11-openjdk-amd64" ]; then
        export JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
    elif command -v javac >/dev/null 2>&1; then
        JAVA_BIN=$(readlink -f $(command -v javac))
        export JAVA_HOME=$(dirname $(dirname "$JAVA_BIN"))
    else
        echo "Error: JAVA_HOME not set and could not be determined automatically"
        echo "Please set JAVA_HOME to your WSL Java installation:"
        echo "  export JAVA_HOME=\"/usr/lib/jvm/java-11-openjdk-amd64\""
        exit 1
    fi
fi

if [ ! -d "$JAVA_HOME/include" ]; then
    echo "Error: JAVA_HOME ($JAVA_HOME) does not contain include directory"
    echo "Please set JAVA_HOME to a valid JDK installation"
    exit 1
fi

# Check for RISC-V cross-compiler
if ! command -v riscv64-linux-gnu-gcc >/dev/null 2>&1; then
    echo "Error: RISC-V cross-compiler not found"
    echo "Please install it with: sudo apt install gcc-riscv64-linux-gnu"
    exit 1
fi

echo "Using JAVA_HOME: $JAVA_HOME"
echo "Target Architecture: RISC-V 64-bit"
echo "Cross-Compiler: $(which riscv64-linux-gnu-gcc)"

# Go to cc folder
cd cc

# Compile the C file using RISC-V cross-compiler
# Note: Using x86 Java headers is fine - jni.h is architecture-agnostic
echo "Compiling sha3accelerator_jni.c..."
riscv64-linux-gnu-gcc -c -fPIC -O2 -Wall -D_GNU_SOURCE -std=gnu11 \
    -I${JAVA_HOME}/include \
    -I${JAVA_HOME}/include/linux \
    sha3accelerator_jni.c -o sha3accelerator_jni.o

if [ $? -ne 0 ]; then
    echo "Compilation failed!"
    exit 1
fi

# Create shared library using RISC-V cross-compiler
echo "Linking libnative.so..."
riscv64-linux-gnu-gcc -shared -fPIC -o libnative.so sha3accelerator_jni.o -lc

if [ $? -ne 0 ]; then
    echo "Linking failed!"
    rm -f sha3accelerator_jni.o
    exit 1
fi

# Copy to lib folder
mv libnative.so ../lib

# Clean up object file
rm -f sha3accelerator_jni.o

echo ""
echo "Build successful! Cross-compiled RISC-V library created: lib/libnative.so"
echo ""
echo "Next steps:"
echo "1. Transfer to FPGA: scp lib/libnative.so root@<fpga_ip>:/root/Minima/jni/lib/"
echo "2. SSH to FPGA and set permissions: chmod +x /root/Minima/jni/lib/libnative.so"
echo "3. Run Minima on FPGA (ensure /dev/mem permissions if needed)"
