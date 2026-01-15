/*
 * SHA3-256 Software Benchmark - IMPROVED VERSION
 * 
 * This version provides detailed cycle-accurate timing and performance analysis
 * to enable fair comparison with hardware accelerator performance.
 * 
 * Key improvements:
 * 1. Cycle-accurate timing using RISC-V rdcycle
 * 2. Detailed timing breakdown
 * 3. Performance analysis and theoretical estimates
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

// ========== Software SHA3-256 Implementation ==========
#define SHA3_256_RATE 136

// Read CPU cycle counter (RISC-V)
static inline uint64_t read_cycles(void) {
    uint64_t cycles;
    asm volatile ("rdcycle %0" : "=r" (cycles));
    return cycles;
}

static const uint64_t keccakf_rndc[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808aULL,
    0x8000000080008000ULL, 0x000000000000808bULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008aULL,
    0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000aULL,
    0x000000008000808bULL, 0x800000000000008bULL, 0x8000000000008089ULL,
    0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800aULL, 0x800000008000000aULL, 0x8000000080008081ULL,
    0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL
};

static const int keccakf_rotc[24] = {
    1,  3,  6,  10, 15, 21, 28, 36, 45, 55, 2,  14,
    27, 41, 56, 8,  25, 43, 62, 18, 39, 61, 20, 44
};

static const int keccakf_piln[24] = {
    10, 7,  11, 17, 18, 3, 5,  16, 8,  21, 24, 4,
    15, 23, 19, 13, 12, 2, 20, 14, 22, 9,  6,  1
};

#define ROTL64(x, y) (((x) << (y)) | ((x) >> (64 - (y))))

static void keccakf(uint64_t st[25]) {
    uint64_t t, bc[5];
    for (int round = 0; round < 24; round++) {
        for (int i = 0; i < 5; i++)
            bc[i] = st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20];
        for (int i = 0; i < 5; i++) {
            t = bc[(i + 4) % 5] ^ ROTL64(bc[(i + 1) % 5], 1);
            for (int j = 0; j < 25; j += 5)
                st[j + i] ^= t;
        }
        t = st[1];
        for (int i = 0; i < 24; i++) {
            int j = keccakf_piln[i];
            bc[0] = st[j];
            st[j] = ROTL64(t, keccakf_rotc[i]);
            t = bc[0];
        }
        for (int j = 0; j < 25; j += 5) {
            for (int i = 0; i < 5; i++)
                bc[i] = st[j + i];
            for (int i = 0; i < 5; i++)
                st[j + i] ^= (~bc[(i + 1) % 5]) & bc[(i + 2) % 5];
        }
        st[0] ^= keccakf_rndc[round];
    }
}

static void sha3_256_sw(const uint8_t *input, size_t len, uint8_t output[32]) {
    uint64_t state[25] = {0};
    size_t rate_bytes = SHA3_256_RATE;
    size_t idx = 0;
    while (len >= rate_bytes) {
        for (size_t i = 0; i < rate_bytes / 8; i++) {
            uint64_t word = 0;
            for (int j = 0; j < 8; j++)
                word |= ((uint64_t)input[idx++]) << (8 * j);
            state[i] ^= word;
        }
        keccakf(state);
        len -= rate_bytes;
    }
    // Use static array to avoid stack allocation overhead on each call
    // This reduces cache pressure and initialization cost
    static uint8_t temp[SHA3_256_RATE];
    memset(temp, 0, SHA3_256_RATE);
    for (size_t i = 0; i < len; i++)
        temp[i] = input[idx++];
    temp[len] = 0x06;
    temp[rate_bytes - 1] |= 0x80;
    for (size_t i = 0; i < rate_bytes / 8; i++) {
        uint64_t word = 0;
        for (int j = 0; j < 8; j++)
            word |= ((uint64_t)temp[i * 8 + j]) << (8 * j);
        state[i] ^= word;
    }
    keccakf(state);
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 8; j++)
            output[i * 8 + j] = (state[i] >> (8 * j)) & 0xFF;
    }
}

static int sha3_256_sw_with_timing(const uint8_t *input, size_t len, 
                                     uint8_t output[32], 
                                     uint64_t *compute_cycles) {
    uint64_t start, end;
    
    // === COMPUTE PHASE ===
    start = read_cycles();
    
    sha3_256_sw(input, len, output);
    
    end = read_cycles();
    *compute_cycles = end - start;
    
    return 0;
}


void analyze_computation_complexity(size_t input_len) {
    printf("\n========================================\n");
    printf("Computation Complexity Analysis\n");
    printf("========================================\n");
    
    // Estimate computational workload for SHA3-256 with user-defined input length
    size_t rate_bytes = 136;
    size_t num_blocks = (input_len + rate_bytes - 1) / rate_bytes;  // ceil division
    
    printf("\nFor %zu-byte input:\n", input_len);
    printf("  Rate (SHA3-256):    %zu bytes\n", rate_bytes);
    printf("  Number of blocks:   %zu\n", num_blocks);
    printf("  Keccak-f rounds:    24 rounds per block\n");
    printf("  Total keccak-f:     %zu blocks × 24 rounds = %zu rounds\n", 
           num_blocks, num_blocks * 24);
    
    printf("\nKeccak-f round operations:\n");
    printf("  Theta step:         25 XORs + 10 rotations\n");
    printf("  Rho/Pi step:        24 rotations + 25 copies\n");
    printf("  Chi step:           25 XORs + 50 ANDs + 25 NOTs\n");
    printf("  Iota step:          1 XOR with round constant\n");
    printf("  Total per round:    ~125 operations on 64-bit words\n");
    printf("  Total operations:   ~%zu operations\n", num_blocks * 24 * 125);
    
    printf("\nPerformance factors:\n");
    printf("  1. Cache locality: State array (200 bytes) fits in L1 cache\n");
    printf("  2. Instruction-level parallelism: Many operations can pipeline\n");
    printf("  3. Memory access: Sequential input reads, random state access\n");
    printf("  4. Branch prediction: Predictable loop structure\n");
}

int main(int argc, char **argv) {
    size_t data_size = 850;
    size_t num_iterations = 10000;

    // Parse command line arguments
    if (argc >= 2) {
        data_size = (size_t)atoi(argv[1]);
        if (data_size <= 0) data_size = 850; // Safety fallback
    }
    if (argc >= 3) {
        num_iterations = (size_t)atoi(argv[2]);
        if (num_iterations <= 0) num_iterations = 10000;
    }
    
    uint8_t *input = (uint8_t *)malloc(data_size);
    uint8_t hash[32];
    
    // Fill with test pattern
    for (size_t i = 0; i < data_size; i++) {
        input[i] = (uint8_t)(i & 0xFF);
    }
    
    printf("========================================\n");
    printf("SHA3-256 Software Benchmark - Improved\n");
    printf("========================================\n");
    printf("Usage: %s [input_size] [iterations]\n", argv[0]);
    printf("Data size: %zu bytes\n", data_size);
    printf("Number of hashes: %zu\n", num_iterations);
    
    // Warm-up phase: Run a few iterations to warm up caches, branch predictors, and CPU
    // This ensures consistent timing regardless of NUM_ITERATIONS
    printf("\nWarming up (cache, branch predictor, CPU frequency)...\n");
    const size_t WARMUP_ITERATIONS = 1000; // Reduced cleanup for speed
    for (size_t i = 0; i < WARMUP_ITERATIONS; i++) {
        sha3_256_sw(input, data_size, hash);
    }
    printf("Warmup complete.\n\n");
    
    printf("Starting benchmark...\n\n");
    
    uint64_t total_compute = 0;
    uint64_t overall_start = read_cycles();
    
    for (size_t i = 0; i < num_iterations; i++) {
        uint64_t compute;
        sha3_256_sw_with_timing(input, data_size, hash, &compute);
        total_compute += compute;
    }
    
    uint64_t overall_end = read_cycles();
    uint64_t total_cycles = overall_end - overall_start;
    
    // Calculate averages
    double avg_compute = (double)total_compute / num_iterations;
    double avg_total = (double)total_cycles / num_iterations;
    
    // Calculate time and throughput
    uint32_t sys_clk_freq = 100000000;  // 100 MHz (assumed CPU frequency)
    double time_per_hash = avg_total / sys_clk_freq * 1e6;  // μs
    double throughput = (data_size * num_iterations) / ((double)total_cycles / sys_clk_freq) / (1024.0 * 1024.0);
    
    printf("Timing Breakdown (average per hash):\n");
    printf("  Compute phase:        %8.0f cycles (%5.1f%%)\n", 
           avg_compute, (avg_compute / avg_total) * 100.0);
    printf("  Total:                %8.0f cycles\n", avg_total);
    
    printf("\nPerformance:\n");
    printf("  Time per hash:       %8.2f μs\n", time_per_hash);
    printf("  Throughput:          %8.6f MB/s\n", throughput);
    printf("  Hash rate:           %8.6f MH/s\n", num_iterations / ((double)total_cycles / sys_clk_freq) / 1e6);
    printf("  Cycles per byte:     %8.2f cycles/byte\n", avg_total / data_size);
    
    printf("\nFinal hash: ");
    for (int i = 0; i < 8; i++) printf("%02x", hash[i]);
    printf("...\n");
    
    // Computation complexity analysis
    analyze_computation_complexity(data_size);
    
    free(input);
    return 0;
}

