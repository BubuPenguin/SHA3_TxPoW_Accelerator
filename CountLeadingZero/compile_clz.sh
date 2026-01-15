#!/bin/bash

# Compilation script for test_clz_accelerator.c
# Run this to compile the C test for the FPGA with CLZ-based mining

echo "Compiling test_clz_accelerator.c for RISC-V..."
riscv64-linux-gnu-gcc -o test_clz_accelerator test_clz_accelerator.c -static

if [ $? -eq 0 ]; then
    echo "✓ Compilation successful: test_clz_accelerator"
    echo ""
    echo "Usage:"
    echo "  ./test_clz_accelerator [target_clz] [timeout_cycles] [input_size] [attempt_limit]"
    echo ""
    echo "Parameters:"
    echo "  target_clz:     Number of leading zeros (difficulty), default=8"
    echo "  timeout_cycles: Timeout in cycles, 0=disabled, default=0"
    echo "  input_size:     Input data size in bytes (1-2176), default=100"
    echo "  attempt_limit:  Max attempts/nonces to try, 0=disabled, default=0"
    echo ""
    echo "Examples:"
    echo "  ./test_clz_accelerator 8                 # Easy: 8 leading zeros"
    echo "  ./test_clz_accelerator 16 0 200          # Medium: 200 byte input"
    echo "  ./test_clz_accelerator 20 10000000 100 0 # Hard, 10M cycle timeout"
    echo "  ./test_clz_accelerator 8 0 100 1000      # 100 byte input, limit 1000 attempts"
    echo ""
    echo "To deploy to FPGA:"
    echo "  1. Copy to FPGA: scp test_clz_accelerator root@<fpga_ip>:~/"
    echo "  2. Run on FPGA:  ./test_clz_accelerator 8"
else
    echo "✗ Compilation failed"
    exit 1
fi

