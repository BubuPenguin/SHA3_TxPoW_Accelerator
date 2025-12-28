#!/bin/bash

# Compilation script for test_fixed_iteration.c
# Run this to compile the C test for the FPGA

echo "Compiling test_fixed_iteration.c for RISC-V..."
riscv64-linux-gnu-gcc -o test_fixed_iteration test_fixed_iteration.c -static

if [ $? -eq 0 ]; then
    echo "✓ Compilation successful: test_fixed_iteration"
    echo ""
    echo "To run on FPGA:"
    echo "  1. Copy to FPGA: scp test_fixed_iteration root@<fpga_ip>:~/"
    echo "  2. Run on FPGA:  ./test_fixed_iteration"
else
    echo "✗ Compilation failed"
    exit 1
fi

