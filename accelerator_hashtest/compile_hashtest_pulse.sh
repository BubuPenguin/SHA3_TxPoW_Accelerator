#!/bin/bash

# Compilation script for hashtest_pulse.c
echo "Compiling hashtest_pulse.c for RISC-V..."
riscv64-linux-gnu-gcc -o hashtest_pulse hashtest_pulse.c -static

if [ $? -eq 0 ]; then
    echo "✓ Compilation successful: hashtest_pulse"
else
    echo "✗ Compilation failed"
    exit 1
fi
