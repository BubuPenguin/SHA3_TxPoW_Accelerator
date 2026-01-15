#!/bin/bash

# Compilation script for hashtest_attempts.c
# Run this to compile the C benchmark for the RISC-V system

echo "Compiling hashtest_attempts.c for RISC-V..."
riscv64-linux-gnu-gcc -o hashtest_attempts hashtest_attempts.c -static

if [ $? -eq 0 ]; then
    echo "✓ Compilation successful: hashtest_attempts"
    echo ""
    echo "Usage:"
    echo "  ./hashtest_attempts [input_size]"
    echo ""
    echo "Example:"
    echo "  ./hashtest_attempts 1000     # Run benchmark with 1000 byte input"
    echo ""
    echo "Output:"
    echo "  Writes results to benchmark_results.csv"
else
    echo "✗ Compilation failed"
    exit 1
fi
