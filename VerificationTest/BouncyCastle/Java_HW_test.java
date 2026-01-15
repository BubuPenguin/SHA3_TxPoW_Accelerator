import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.util.Arrays;
import org.bouncycastle.crypto.Digest;
import org.bouncycastle.crypto.digests.SHA3Digest;

public class Java_HW_test {

    /**
     * Software-only SHA3-256 verification test
     * (Hardware JNI interface removed for simplicity)
     */

    /**
     * Generate test header data matching the C test pattern
     */
    public static byte[] generateTestHeader(int length) {
        byte[] header = new byte[length];
        byte[] pattern = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, (byte)0x88};
        
        // Fill with repeating pattern
        for (int i = 0; i < length; i++) {
            header[i] = pattern[i % pattern.length];
        }
        
        // Set nonce field structure (bytes 0-33)
        header[0] = 1;   // Scale field
        header[1] = 32;  // Length field
        
        // Nonce data field (bytes 2-33) - initialize to zero
        for (int i = 2; i < 34 && i < length; i++) {
            header[i] = 0;
        }
        
        return header;
    }

    /**
     * Insert a nonce value into the header data
     * Nonce structure (matching hardware accelerator):
     *   - Byte 0: Scale field (NOT overwritten)
     *   - Byte 1: Length field (NOT overwritten)
     *   - Bytes 2-3: Spacing (NOT overwritten)
     *   - Bytes 4-33: 30-byte nonce (OVERWRITTEN)
     * 
     * @param header Original header data
     * @param nonce 30-byte nonce to insert (or longer, only first 30 bytes used)
     * @return Modified header with nonce inserted
     */
    public static byte[] insertNonce(byte[] header, byte[] nonce) {
        byte[] result = header.clone();
        
        // Overwrite bytes 4-33 with nonce data (30 bytes)
        int nonceLength = Math.min(nonce.length, 30);
        System.arraycopy(nonce, 0, result, 4, nonceLength);
        
        return result;
    }

    /**
     * Extract nonce from hardware nonce_result register (32 bytes)
     * Register format: {30-byte nonce, 2-byte spacing}
     *   - Bytes 0-1: Spacing from header bytes [2:3] (not overwritten)
     *   - Bytes 2-31: 30-byte nonce data
     * 
     * @param nonceResult 32-byte nonce_result from hardware
     * @return 30-byte nonce (bytes 2-31 of register)
     */
    public static byte[] extractNonceFromResult(byte[] nonceResult) {
        if (nonceResult.length != 32) {
            throw new IllegalArgumentException("Nonce result must be 32 bytes");
        }
        
        // Extract the 30-byte nonce (skip first 2 bytes which are spacing)
        byte[] nonce = new byte[30];
        System.arraycopy(nonceResult, 2, nonce, 0, 30);
        return nonce;
    }

    /**
     * Parse a nonce from hex string
     * @param hexString Hex string (with or without 0x prefix)
     * @return Byte array of nonce data
     */
    public static byte[] parseNonceHex(String hexString) {
        // Remove 0x prefix if present
        if (hexString.startsWith("0x") || hexString.startsWith("0X")) {
            hexString = hexString.substring(2);
        }
        
        // Remove spaces
        hexString = hexString.replaceAll("\\s+", "");
        
        int len = hexString.length();
        byte[] data = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            data[i / 2] = (byte) ((Character.digit(hexString.charAt(i), 16) << 4)
                                 + Character.digit(hexString.charAt(i+1), 16));
        }
        return data;
    }

    public static void main(String[] args) {
        System.out.println("========================================");
        System.out.println("SHA3-256 Hash Comparison Test");
        System.out.println("========================================");
        
        // Default values
        int inputSize = 100;  // Default 100 bytes (matches C test default)
        byte[] nonceToInsert = null;
        
        // Parse command line arguments
        // Usage: java Java_HW_test [input_size] [nonce_hex]
        if (args.length >= 1) {
            try {
                inputSize = Integer.parseInt(args[0]);
                if (inputSize < 1 || inputSize > 2176) {
                    System.err.println("ERROR: input_size must be between 1 and 2176 bytes");
                    System.err.println("Usage: java Java_HW_test [input_size] [nonce_hex]");
                    return;
                }
                System.out.println("Input size: " + inputSize + " bytes");
            } catch (NumberFormatException e) {
                System.err.println("ERROR: Invalid input_size format");
                System.err.println("Usage: java Java_HW_test [input_size] [nonce_hex]");
                System.err.println("Example: java Java_HW_test 200 0000005EC244FCABD705DDEBC5F640477D87061E1968787A96E797161CB3C917");
                return;
            }
        }
        
        if (args.length >= 2) {
            System.out.println("Nonce provided via command line");
            try {
                nonceToInsert = parseNonceHex(args[1]);
                System.out.println("Parsed nonce: " + nonceToInsert.length + " bytes");
            } catch (Exception e) {
                System.err.println("ERROR: Failed to parse nonce hex string");
                System.err.println("Usage: java Java_HW_test [input_size] [nonce_hex]");
                System.err.println("Example: java Java_HW_test 200 0000005EC244FCABD705DDEBC5F640477D87061E1968787A96E797161CB3C917");
                return;
            }
        }
        
        // Generate test header with specified size
        // Pattern: [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88] repeated
        // Bytes 0-1: nonce structure (scale=1, length=32)
        // Bytes 2-33: nonce field (zeros initially)
        // Bytes 34+: repeating pattern
        byte[] baseHeader = generateTestHeader(inputSize);
        
        // Apply nonce if provided
        byte[] dataToHash;
        if (nonceToInsert != null) {
            System.out.println("Inserting " + nonceToInsert.length + "-byte nonce into header...");
            System.out.println();
            
            System.out.println("Base Header Data (before nonce insertion):");
            System.out.println("Input data length: " + baseHeader.length + " bytes");
            displayHexDump(baseHeader);
            System.out.println();
            
            dataToHash = insertNonce(baseHeader, nonceToInsert);
            
            System.out.println("Modified Header Data (after nonce insertion):");
            System.out.println("Input data length: " + dataToHash.length + " bytes");
            System.out.println("Note: Bytes 4-33 overwritten with nonce");
            displayHexDump(dataToHash);
        } else {
            dataToHash = baseHeader;
            System.out.println("Using base header (no nonce inserted)");
            System.out.println();
            System.out.println("Input Header Data:");
            System.out.println("Input data length: " + dataToHash.length + " bytes");
            displayHexDump(dataToHash);
        }
        System.out.println();

        // 1. SOFTWARE CALCULATION
        System.out.println("--- SOFTWARE HASH (BouncyCastle) ---");
        byte[] softwareHash = hashData_Software(dataToHash);
        
        StringBuilder swHex = new StringBuilder();
        if (softwareHash != null) {
            for (byte b : softwareHash) swHex.append(String.format("%02X", b));
        }
        System.out.println("Software Hash (Hex): 0x" + swHex.toString());
        System.out.println();

        // 2. RESULT
        System.out.println("========================================");
        System.out.println("Software hash computation completed");
        System.out.println("========================================");
        
        // 4. USAGE EXAMPLES
        if (args.length == 0) {
            System.out.println();
            System.out.println("Usage: java Java_HW_test [input_size] [nonce_hex]");
            System.out.println("  input_size: Input data size in bytes (1-2176, default: 100)");
            System.out.println("  nonce_hex:  30-byte nonce in hex format (optional)");
            System.out.println();
            System.out.println("To verify a hardware result:");
            System.out.println("  1. Read nonce_result from hardware (32 bytes)");
            System.out.println("  2. Extract the 30-byte nonce (bytes 2-31 of register)");
            System.out.println("  3. Run: java Java_HW_test <input_size> <nonce_hex>");
            System.out.println();
            System.out.println("Examples:");
            System.out.println("  java Java_HW_test");
            System.out.println("  java Java_HW_test 200");
            System.out.println("  java Java_HW_test 200 0000005EC244FCABD705DDEBC5F640477D87061E1968787A96E797161CB3C917");
        }
    }

    public static byte[] hashData_Software(byte[] zData) {
        try {
            Digest sha3 = new SHA3Digest(256);
            byte[] output = new byte[sha3.getDigestSize()];
            sha3.update(zData, 0, zData.length);
            sha3.doFinal(output, 0);
            return output;
        } catch (Exception exc) {
            exc.printStackTrace();
        }
        return null;
    }

    /**
     * Display hex dump of byte array (16 bytes per row)
     */
    public static void displayHexDump(byte[] data) {
        for (int i = 0; i < data.length; i += 16) {
            System.out.printf("  [%04x] ", i);
            
            // Print hex values
            for (int j = 0; j < 16; j++) {
                if (i + j < data.length) {
                    System.out.printf("%02x ", data[i + j] & 0xFF);
                } else {
                    System.out.print("   ");
                }
                if (j == 7) System.out.print(" ");
            }
            
            // Print ASCII representation
            System.out.print(" |");
            for (int j = 0; j < 16 && (i + j) < data.length; j++) {
                byte b = data[i + j];
                char c = (b >= 32 && b < 127) ? (char)b : '.';
                System.out.print(c);
            }
            System.out.println("|");
        }
    }
}