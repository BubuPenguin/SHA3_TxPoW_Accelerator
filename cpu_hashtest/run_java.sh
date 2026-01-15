#!/bin/bash
# Run Java SHA3 Benchmark on FPGA/Target

# Expects Bouncy Castle JAR to be in the SAME directory
BC_JAR="bcprov-jdk18on-1.76.jar"

if [ ! -f "$BC_JAR" ]; then
    echo "Error: $BC_JAR not found in current directory."
    echo "Please transfer it to this folder."
    exit 1
fi

INPUT_SIZE=${1:-1024}
ITERATIONS=${2:-1000000}

echo "Running Benchmark (Size=$INPUT_SIZE, Iters=$ITERATIONS)..."
java -cp "Sha3Bench.jar:$BC_JAR" Sha3Bench $INPUT_SIZE $ITERATIONS
