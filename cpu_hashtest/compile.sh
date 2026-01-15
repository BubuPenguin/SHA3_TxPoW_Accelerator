#!/bin/bash
# Compile the Software SHA3 Benchmark for RISC-V

echo "Compiling sha3_bench_sw.c..."

# Use riscv64-linux-gnu-gcc because it includes the necessary C standard libraries (glibc/newlib).
# Use -static to create a standalone binary that doesn't depend on dynamic libraries on the target.
riscv64-linux-gnu-gcc -O3 -Wall -static -o sha3_bench_sw sha3_bench_sw.c

# Check if compilation was successful
if [ $? -eq 0 ]; then
    echo "Compilation successful: sha3_bench_sw"
    echo "To run on the FPGA (via litex_term):"
    echo "  litex_term --kernel sha3_bench_sw /dev/ttyUSBx"
else
    echo "Compilation failed!"
    exit 1
fi
