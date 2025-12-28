#!/bin/bash
# Script to compile the Java SHA3 hardware test

BCPROV_JAR="bcprov-jdk18on-1.76.jar"

# Check if BouncyCastle JAR exists
if [ ! -f "$BCPROV_JAR" ]; then
    echo "ERROR: BouncyCastle JAR not found: $BCPROV_JAR"
    echo ""
    echo "Download it with:"
    echo "  wget https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk18on/1.76/bcprov-jdk18on-1.76.jar"
    echo ""
    echo "Or from: https://www.bouncycastle.org/latest_releases.html"
    exit 1
fi

echo "Compiling Java_HW_test.java..."
# Compile with Java 11 compatibility (class file version 55.0)
# Using --release 11 instead of -source/-target to avoid warnings
javac --release 11 -cp "$BCPROV_JAR:." Java_HW_test.java

if [ $? -ne 0 ]; then
    echo "ERROR: Compilation failed!"
    exit 1
fi

echo "Compilation successful!"
echo ""
echo "Run tests with:"
echo "  ./verify_nonce.sh              # Run basic test (no nonce)"
echo "  ./verify_nonce.sh <nonce_hex>  # Verify hardware nonce"

