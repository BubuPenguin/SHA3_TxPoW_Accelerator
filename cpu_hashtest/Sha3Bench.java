
import java.security.Security;
import org.bouncycastle.crypto.digests.SHA3Digest;
import org.bouncycastle.jce.provider.BouncyCastleProvider;
import java.util.Arrays;

public class Sha3Bench {

    private static final int SHA3_256_RATE = 136;

    public static void main(String[] args) {
        // Default values
        int dataSize = 1024;
        long numIterations = 1000000;

        // Parse arguments
        if (args.length >= 1) {
            try {
                dataSize = Integer.parseInt(args[0]);
                if (dataSize <= 0)
                    dataSize = 1024;
            } catch (NumberFormatException e) {
                System.err.println("Invalid data size. Using default.");
            }
        }
        if (args.length >= 2) {
            try {
                numIterations = Long.parseLong(args[1]);
                if (numIterations <= 0)
                    numIterations = 1000000;
            } catch (NumberFormatException e) {
                System.err.println("Invalid iterations. Using default.");
            }
        }

        System.out.println("========================================");
        System.out.println("SHA3-256 Java (Bouncy Castle) Benchmark");
        System.out.println("========================================");
        System.out.println("Data size: " + dataSize + " bytes");
        System.out.println("Number of hashes: " + numIterations);

        // Prepare input data
        byte[] input = new byte[dataSize];
        for (int i = 0; i < dataSize; i++) {
            input[i] = (byte) (i & 0xFF);
        }

        // Initialize Bouncy Castle (optional if only using lightweight API, but good
        // practice)
        Security.addProvider(new BouncyCastleProvider());

        System.out.println("Starting benchmark...\n");

        long startTime = System.nanoTime();

        for (long i = 0; i < numIterations; i++) {
            performHash(input);
        }

        long endTime = System.nanoTime();
        long totalTimeNs = endTime - startTime;

        // Calculations
        double totalTimeSec = totalTimeNs / 1_000_000_000.0;
        double avgTimeUs = (totalTimeNs / (double) numIterations) / 1000.0;
        double throughputMBs = ((double) dataSize * numIterations) / totalTimeSec / (1024 * 1024);
        double hashRateMHs = (numIterations / totalTimeSec) / 1_000_000.0;

        System.out.println("Performance:");
        System.out.printf("  Total Time:          %.4f s%n", totalTimeSec);
        System.out.printf("  Time per hash:       %.2f μs%n", avgTimeUs);
        System.out.printf("  Throughput:          %.6f MB/s%n", throughputMBs);
        System.out.printf("  Hash rate:           %.6f MH/s%n", hashRateMHs);

        // Print final hash for verification
        byte[] finalHash = performHash(input);
        System.out.print("\nFinal hash: ");
        for (int i = 0; i < 8; i++) {
            System.out.printf("%02x", finalHash[i]);
        }
        System.out.println("...");
    }

    private static byte[] performHash(byte[] input) {
        // Re-implementing the padding-in-software logic from the C benchmark
        // to fully match the workload if needed?
        // Actually, the C benchmark does:
        // 1. Process full blocks
        // 2. Creates a temp buffer for the last block
        // 3. Adds 0x06 and 0x80 padding
        // 4. Processes the last block
        //
        // However, standard libraries like BouncyCastle usually handle padding
        // internally.
        // BUT, Minima uses KECCAK padding conventions (0x06 domain) or Standard SHA3?
        // The request showed: Digest sha3 = new SHA3Digest(256);
        // This is standard SHA3-256 (padding 0x06...0x80).
        // So we can just call update() and doFinal().

        SHA3Digest digest = new SHA3Digest(256);
        digest.update(input, 0, input.length);

        byte[] output = new byte[digest.getDigestSize()];
        digest.doFinal(output, 0);
        return output;
    }
}
