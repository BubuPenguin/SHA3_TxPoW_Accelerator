#!/bin/bash
# Script to run the Java SHA3 hardware test
# Usage: ./verify_nonce.sh                              # Run basic test (100 bytes, no nonce)
#        ./verify_nonce.sh <input_size>                 # Test with custom input size
#        ./verify_nonce.sh <input_size> <nonce_hex>     # Verify hardware nonce

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

# Check if Java code is compiled
if [ ! -f "Java_HW_test.class" ]; then
    echo "ERROR: Java_HW_test.class not found"
    echo "Compile first with: ./compile.sh"
    exit 1
fi

# Case 1: No arguments - run basic test (100 bytes, no nonce)
if [ $# -eq 0 ]; then
    echo "Running basic SHA3 test (100 bytes, no nonce)..."
    echo ""
    java -Djava.library.path=. -cp "$BCPROV_JAR:." Java_HW_test
    exit 0
fi

# Case 2: Only input size provided
if [ $# -eq 1 ]; then
    INPUT_SIZE="$1"
    echo "Running SHA3 test with $INPUT_SIZE bytes (no nonce)..."
    echo ""
    java -Djava.library.path=. -cp "$BCPROV_JAR:." Java_HW_test "$INPUT_SIZE"
    exit 0
fi

# Case 3: Input size and nonce provided - verify hardware result
INPUT_SIZE="$1"
NONCE_HEX="$2"

# Remove spaces and 0x prefix if present
NONCE_HEX=$(echo "$NONCE_HEX" | tr -d ' ' | sed 's/^0x//i')

# Check length (should be 60 hex chars = 30 bytes)
HEX_LEN=${#NONCE_HEX}
EXPECTED_LEN=60

if [ $HEX_LEN -ne $EXPECTED_LEN ]; then
    echo "WARNING: Nonce hex length is $HEX_LEN chars, expected $EXPECTED_LEN (30 bytes)"
    echo "Expected: 30-byte nonce = 60 hex characters"
    echo "Proceeding anyway..."
    echo ""
fi

echo "Verifying hardware nonce result..."
echo "Input size: $INPUT_SIZE bytes"
echo "Nonce (hex): $NONCE_HEX"
echo ""

java -Djava.library.path=. -cp "$BCPROV_JAR:." Java_HW_test "$INPUT_SIZE" "$NONCE_HEX"
