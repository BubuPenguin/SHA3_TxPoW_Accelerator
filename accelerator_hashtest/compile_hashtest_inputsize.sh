#!/bin/bash

# Compilation script for hashtest_inputsize.c
echo "Compiling hashtest_inputsize.c for RISC-V..."
riscv64-linux-gnu-gcc -o hashtest_inputsize hashtest_inputsize.c -static

if [ $? -eq 0 ]; then
    echo "✓ Compilation successful: hashtest_inputsize"
else
    echo "✗ Compilation failed"
    exit 1
fi
