#!/bin/bash
# Compile Java SHA3 Benchmark (Build Only)

# Path to Bouncy Castle JAR
BC_JAR="../VerificationTest/BouncyCastle/bcprov-jdk18on-1.76.jar"

if [ ! -f "$BC_JAR" ]; then
    echo "Error: Bouncy Castle JAR not found at $BC_JAR"
    exit 1
fi

# Clean previous build
rm -f Sha3Bench.class Sha3Bench.jar

echo "Compiling Sha3Bench.java..."
# Use --release 11 to ensure compatibility with Java 11 Runtime (common on embedded/FPGA)
javac --release 11 -cp ".:$BC_JAR" Sha3Bench.java

if [ $? -eq 0 ]; then
    echo "Creating Sha3Bench.jar..."
    jar cfe Sha3Bench.jar Sha3Bench Sha3Bench.class

    echo "Build successful."
    echo "Artifact created: Sha3Bench.jar"
else
    echo "Compilation failed."
    exit 1
fi
