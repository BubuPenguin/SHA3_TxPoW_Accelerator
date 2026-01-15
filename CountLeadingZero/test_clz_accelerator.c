/**
 * SHA3 TxPoW CLZ Accelerator - FPGA Hardware Test
 * 
 * This test runs on the RISC-V SoC and communicates with the FPGA accelerator
 * via memory-mapped registers at 0xF0000000.
 * 
 * Compile: ./compile_clz.sh
 * Run on hardware: ./test_clz_accelerator [target_clz] [timeout_cycles]
 */

 #include <stdio.h>
 #include <stdlib.h>
 #include <stdint.h>
 #include <string.h>
 #include <unistd.h>
 #include <fcntl.h>
 #include <sys/mman.h>
 #include <time.h>
 
 #define TXPOW_BASE 0xF0000000
 
 /* Configuration */
 #define DEFAULT_INPUT_SIZE   100    // Default input header size in bytes (max 2176 = 16 blocks)
 #define MAX_INPUT_SIZE      2176    // Maximum: 16 blocks × 136 bytes/block
 
 /* Register Offsets */
 #define REG_CONTROL          0x000
 #define REG_STATUS           0x004
 #define REG_NONCE_RESULT     0x008  // 256-bit result (8 words = 32 bytes)
 #define REG_HASH_RESULT      0x028  // 256-bit result (8 words = 32 bytes)
 #define REG_ITERATION_COUNT  0x048  // 64-bit status (2 words)
 #define REG_TARGET_CLZ       0x050  
 #define REG_DEBUG_HASH0      0x054  // 256-bit (8 words)
 #define REG_DEBUG_HASH1      0x074  // 256-bit (8 words)
 #define REG_DEBUG_CLZ0       0x094  
 #define REG_DEBUG_CLZ1       0x098  
 #define REG_DEBUG_COMPARISON 0x09C  
 #define REG_DEBUG_BLOCK0     0x0A0  // Debug: First 64 bytes of block 0 (16 words = 64 bytes)
 #define REG_TIMEOUT          0x0E0  // 64-bit register (2 words) - Clock cycles
 #define REG_ATTEMPT_LIMIT    0x0E8  // 64-bit register (2 words) - Max Attempts (NEW)
 #define REG_INPUT_LEN        0x0F0
 #define REG_HEADER_DATA_LOW  0x0F4  // Low 32 bits of 64-bit header word
 #define REG_HEADER_DATA_HIGH 0x0F8  // High 32 bits of 64-bit header word
 #define REG_HEADER_ADDR      0x0FC  // Word address (0-271 for 2176 bytes)
 #define REG_HEADER_WE        0x100  // Write enable
 
 #define STATUS_IDLE    (1 << 0)
 #define STATUS_RUNNING (1 << 1)
 #define STATUS_FOUND   (1 << 2)
 #define STATUS_TIMEOUT (1 << 3)
 
 static volatile uint32_t *regs = NULL;
 
 // Read CPU cycle counter (RISC-V)
 static inline uint64_t read_cycles(void) {
     uint64_t cycles;
     asm volatile ("rdcycle %0" : "=r" (cycles));
     return cycles;
 }
 
 
 int init_hw(void) {
     int fd = open("/dev/mem", O_RDWR | O_SYNC);
     if (fd < 0) return -1;
     regs = (volatile uint32_t *)mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, TXPOW_BASE);
     return (regs == MAP_FAILED) ? -1 : 0;
 }
 
 void write_header_data(const uint8_t *data, size_t length) {
     printf("Writing %zu bytes of header data (Multi-block aware)...\n", length);
     
     // The hardware memory is organized as 272 words (64-bit each)
     // Total capacity is 2176 bytes (16 blocks * 136 bytes)
     size_t num_words = (length + 7) / 8;  // Round up to nearest 8 bytes
     
     for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
         uint64_t word = 0;
         
         // Pack 8 bytes into a 64-bit word
         // This ensures data[0] is at the least significant bits of word 0
         for (int byte_offset = 0; byte_offset < 8; byte_offset++) {
             size_t global_byte_idx = (word_idx * 8) + byte_offset;
             
             if (global_byte_idx < length) {
                 // Shift byte into its position within the 64-bit word
                 word |= ((uint64_t)data[global_byte_idx]) << (byte_offset * 8);
             }
         }
         
         // Split 64-bit word into two 32-bit registers for the CSR interface
         uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
         uint32_t high = (uint32_t)(word >> 32);
         
         // Write sequence: Address -> Low Data -> High Data -> Trigger WE
         regs[REG_HEADER_ADDR / 4]      = (uint32_t)word_idx;
         regs[REG_HEADER_DATA_LOW / 4]  = low;
         regs[REG_HEADER_DATA_HIGH / 4] = high;
         
         // Ensure registers are updated before triggering Write Enable
         __sync_synchronize();
         regs[REG_HEADER_WE / 4] = 1;
         
         // Small delay to allow FPGA logic to capture data into memory
         for (volatile int delay = 0; delay < 20; delay++);
         
         regs[REG_HEADER_WE / 4] = 0;
         __sync_synchronize();
     }
     
     printf("Header data transfer complete. Words written: %zu\n", num_words);
 }
 
 void generate_test_header(uint8_t *buffer, size_t length) {
     // Repeating pattern
     uint8_t pattern[] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
     
     // Fill with repeating pattern
     for (size_t i = 0; i < length; i++) {
         buffer[i] = pattern[i % 8];
     }
     
     // Set nonce field structure (bytes 0-33)
     buffer[0] = 1;   // Scale field
     buffer[1] = 32;  // Length field
     
     // Nonce data field (bytes 2-33) - initialize to zero
     for (int i = 2; i < 34; i++) {
         buffer[i] = 0;
     }
 }
 
void display_header_data(const uint8_t *data, size_t length) {
    printf("Input Header: %zu bytes (nonce field at bytes 0-33)\n", length);
}

/**
 * Determine which block number is being shown based on the data pattern.
 * Block 0 has header structure (0x01, 0x20 at bytes 0-1) and may have nonce in bytes 4-33.
 * Block 1+ has raw pattern data (0x11, 0x22 pattern) or other data.
 * 
 * Returns: 0 for block 0, 1+ for subsequent blocks
 */
int determine_block_number(const uint8_t *block_data, int input_size) {
    // Block 0 has header structure: bytes 0-1 are 0x01, 0x20
    // (Note: if nonce was injected, bytes 4-33 will have nonce data, but bytes 0-1 should still be 0x01, 0x20)
    if (block_data[0] == 0x01 && block_data[1] == 0x20) {
        return 0;
    }
    
    // Block 1+ starts at byte 136 of the input
    // For 150-byte input, block 1 would be bytes 136-149 (14 bytes)
    // The debug register shows 64 bytes, so:
    // - Bytes 0-13 = actual block 1 data (bytes 136-149 of input)
    // - Bytes 14-63 = padding/zeros (beyond input_size)
    
    uint8_t pattern[] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
    
    // If bytes 0-1 match the pattern (0x11, 0x22), it's block 1+
    if (block_data[0] == pattern[0] && block_data[1] == pattern[1]) {
        // This matches the pattern starting at byte 136, so it's block 1
        return 1;
    }
    
    // Check if all zeros (could be block 1 with padding beyond input_size)
    int all_zeros = 1;
    for (int i = 0; i < 64; i++) {
        if (block_data[i] != 0) {
            all_zeros = 0;
            break;
        }
    }
    
    if (all_zeros) {
        // All zeros: This is NOT block 0 (which would have 0x01, 0x20 header)
        // If input_size > 136, block 1 exists and this could be it (with padding)
        // If input_size <= 136, there's no block 1, so this must be block 0 (unlikely but possible)
        if (input_size > 136) {
            return 1;  // Block 1 exists - all zeros likely means block 1 with padding
        }
        // If input_size <= 136, there's no block 1, but bytes 0-1 aren't 0x01, 0x20
        // This is an edge case - default to block 0
        return 0;
    }
    
    // If we have non-zero data but it doesn't match block 0 header or block 1 pattern,
    // and input_size > 136, it's likely block 1 with some data
    if (input_size > 136 && block_data[0] != 0x01) {
        return 1;  // Not block 0 header, and block 1 exists
    }
    
    // Default: assume block 0 if we can't determine
    return 0;
}

void run_clz_test(int target_clz, uint64_t timeout_cycles, uint64_t attempt_limit, int input_size, int debug_enabled) {
     printf("\n=== CLZ Mining Test ===\n");
     printf("Target: %d leading zeros | Timeout: %s | Limit: %llu | Input: %d bytes\n", 
            target_clz,
            timeout_cycles == 0 ? "disabled" : "enabled",
            (unsigned long long)attempt_limit,
            input_size);
 
     /* 1. Reset */
     regs[REG_CONTROL / 4] = 2; // Stop
     __sync_synchronize();
     regs[REG_CONTROL / 4] = 0;
     
     /* 2. Setup header */
     uint8_t header_data[MAX_INPUT_SIZE];
     generate_test_header(header_data, input_size);
     display_header_data(header_data, input_size);
     write_header_data(header_data, input_size);
     
     /* 3. Configure */
     regs[REG_TARGET_CLZ / 4] = target_clz;
     regs[REG_INPUT_LEN / 4]  = input_size;
     regs[REG_TIMEOUT / 4]     = (uint32_t)(timeout_cycles >> 32);
     regs[REG_TIMEOUT / 4 + 1] = (uint32_t)(timeout_cycles & 0xFFFFFFFF);
     
     regs[REG_ATTEMPT_LIMIT / 4]     = (uint32_t)(attempt_limit >> 32);
     regs[REG_ATTEMPT_LIMIT / 4 + 1] = (uint32_t)(attempt_limit & 0xFFFFFFFF);
     
     __sync_synchronize();
 
     /* 4. Start */
     printf("Starting mining...\n");
     
     uint64_t start_cycles = read_cycles();
     struct timespec start_time, end_time;
     clock_gettime(CLOCK_MONOTONIC, &start_time);
     
     regs[REG_CONTROL / 4] = 1;
     __sync_synchronize();
 
     /* 5. Monitor */
     uint64_t last_iters = 0;
     uint32_t status = 0;
     int block_iteration = 0;
     uint8_t last_debug_block[64] = {0};
     int expected_blocks = (input_size / 136) + 1;
     
     if (debug_enabled) {
         printf("\n[DEBUG] Monitoring block data for each iteration...\n");
         printf("Expected blocks: %d\n", expected_blocks);
     }
     
     while (1) {
         status = regs[REG_STATUS / 4];
         
         if (status & STATUS_FOUND) {
             printf("\n✓ Solution found!\n");
             
            /* Debug: Read final block data before breaking */
            if (debug_enabled) {
                uint8_t final_debug_block[64];
                // NOTE: LiteX CSRs use BIG-ENDIAN word ordering (MSW first)
                // For a 16-word CSR: CSR[0] = Word[15], CSR[1] = Word[14], ..., CSR[15] = Word[0]
                // Read in reverse order to handle LiteX's big-endian CSR word ordering
                for (int i = 0; i < 16; i++) {
                    uint32_t word = regs[(REG_DEBUG_BLOCK0 / 4) + (15 - i)];
                    final_debug_block[i*4 + 0] = (word >> 0) & 0xFF;
                    final_debug_block[i*4 + 1] = (word >> 8) & 0xFF;
                    final_debug_block[i*4 + 2] = (word >> 16) & 0xFF;
                    final_debug_block[i*4 + 3] = (word >> 24) & 0xFF;
                }
                
                // Always determine and display the block number based on actual data
                int block_num = determine_block_number(final_debug_block, input_size);
                
                /* Check if this is different from last seen block */
                int final_changed = 0;
                for (int i = 0; i < 64; i++) {
                    if (final_debug_block[i] != last_debug_block[i]) {
                        final_changed = 1;
                        break;
                    }
                }
                
                // Always display final block data with correct block number
                printf("\n  [Block %d] Final block data:\n", block_num);
                printf("    Bytes 0-15:   ");
                for (int i = 0; i < 16; i++) {
                    printf("%02X ", final_debug_block[i]);
                }
                printf("\n");
                printf("    Bytes 16-31:  ");
                for (int i = 16; i < 32; i++) {
                    printf("%02X ", final_debug_block[i]);
                }
                printf("\n");
            }
             break;
         }
         
         if (status & STATUS_TIMEOUT) {
             printf("\n✗ Timeout!\n");
             break;
         }
         
         /* Debug: Read block data while running (read every iteration, print on change) */
         if (debug_enabled && (status & STATUS_RUNNING)) {
             uint8_t current_debug_block[64];
             
             /* Read 16 words (64 bytes) from REG_DEBUG_BLOCK0 */
             // NOTE: LiteX CSRs use BIG-ENDIAN word ordering (MSW first)
             // For a 16-word CSR: CSR[0] = Word[15], CSR[1] = Word[14], ..., CSR[15] = Word[0]
             // Read in reverse order to handle LiteX's big-endian CSR word ordering
             for (int i = 0; i < 16; i++) {
                 uint32_t word = regs[(REG_DEBUG_BLOCK0 / 4) + (15 - i)];
                 /* Convert 32-bit word to bytes (little-endian within each word) */
                 current_debug_block[i*4 + 0] = (word >> 0) & 0xFF;
                 current_debug_block[i*4 + 1] = (word >> 8) & 0xFF;
                 current_debug_block[i*4 + 2] = (word >> 16) & 0xFF;
                 current_debug_block[i*4 + 3] = (word >> 24) & 0xFF;
             }
             
             /* Check if this is a new block (data changed) */
             int data_changed = 0;
             for (int i = 0; i < 64; i++) {
                 if (current_debug_block[i] != last_debug_block[i]) {
                     data_changed = 1;
                     break;
                 }
             }
             
            if (data_changed) {
                block_iteration++;
                memcpy(last_debug_block, current_debug_block, 64);
                
                // Determine actual block number from data pattern
                int block_num = determine_block_number(current_debug_block, input_size);
                
                /* Determine if this is Block 0 (has nonce) */
                int is_block_0 = (block_num == 0);
                 printf("\n  [Block %d] First 64 bytes:\n", block_num);
                 printf("    Bytes 0-15:   ");
                 for (int i = 0; i < 16; i++) {
                     printf("%02X ", current_debug_block[i]);
                 }
                 printf("\n");
                 printf("    Bytes 16-31:  ");
                 for (int i = 16; i < 32; i++) {
                     printf("%02X ", current_debug_block[i]);
                 }
                 printf("\n");
                 printf("    Bytes 32-47:  ");
                 for (int i = 32; i < 48; i++) {
                     printf("%02X ", current_debug_block[i]);
                 }
                 printf("\n");
                 printf("    Bytes 48-63:  ");
                 for (int i = 48; i < 64; i++) {
                     printf("%02X ", current_debug_block[i]);
                 }
                 printf("\n");
                 
                 if (block_num == 0) {
                     printf("    [Block 0] Nonce area (bytes 4-33) contains nonce data\n");
                     printf("    Nonce bytes (4-33): ");
                     for (int i = 4; i < 34; i++) {
                         printf("%02X ", current_debug_block[i]);
                     }
                     printf("\n");
                 } else {
                     printf("    [Block %d] Raw block data (no nonce injection)\n", block_num);
                 }
             }
         }
         
         uint32_t high = regs[(REG_ITERATION_COUNT / 4)];
         uint32_t low  = regs[(REG_ITERATION_COUNT / 4) + 1];
         uint64_t current_iters = ((uint64_t)high << 32) | low;
 
         if (current_iters >= last_iters + 100000) {
             printf("  %llu iterations...\n", (unsigned long long)current_iters);
             last_iters = current_iters;
         }
         usleep(50000);
     }
 
     uint64_t end_cycles = read_cycles();
     clock_gettime(CLOCK_MONOTONIC, &end_time);
     
     uint64_t total_cycles = end_cycles - start_cycles;
     double elapsed = (end_time.tv_sec - start_time.tv_sec) + 
                      (end_time.tv_nsec - start_time.tv_nsec) / 1e9;
 
     /* 6. Read results */
     uint32_t final_high = regs[(REG_ITERATION_COUNT / 4)];
     uint32_t final_low  = regs[(REG_ITERATION_COUNT / 4) + 1];
     uint64_t final_iters = ((uint64_t)final_high << 32) | final_low;
 
     uint32_t nonce[8];
     for (int i = 0; i < 8; i++) {
         nonce[i] = regs[(REG_NONCE_RESULT / 4) + (7 - i)];
     }
 
     uint32_t hash[8];
     for (int i = 0; i < 8; i++) {
         hash[i] = regs[(REG_HASH_RESULT / 4) + (7 - i)];
     }
     
     uint32_t debug_clz0 = regs[REG_DEBUG_CLZ0 / 4];
     uint32_t debug_clz1 = regs[REG_DEBUG_CLZ1 / 4];
     uint32_t debug_comparison = regs[REG_DEBUG_COMPARISON / 4];
     
     uint8_t hash_bytes[32];
     for (int i = 0; i < 8; i++) {
         hash_bytes[i*4 + 0] = (hash[i] >> 0) & 0xFF;
         hash_bytes[i*4 + 1] = (hash[i] >> 8) & 0xFF;
         hash_bytes[i*4 + 2] = (hash[i] >> 16) & 0xFF;
         hash_bytes[i*4 + 3] = (hash[i] >> 24) & 0xFF;
     }
     
     uint8_t nonce_bytes[32];
     for (int i = 0; i < 8; i++) {
         nonce_bytes[i*4 + 0] = (nonce[i] >> 0) & 0xFF;
         nonce_bytes[i*4 + 1] = (nonce[i] >> 8) & 0xFF;
         nonce_bytes[i*4 + 2] = (nonce[i] >> 16) & 0xFF;
         nonce_bytes[i*4 + 3] = (nonce[i] >> 24) & 0xFF;
     }
 
     /* 7. Report */
     printf("\n=== Results ===\n");
     printf("Iterations: %llu\n", (unsigned long long)final_iters);
     printf("Time:       %.4f sec\n", elapsed);
     printf("Hash rate:  %.2f MH/s\n", ((double)final_iters / elapsed) / 1e6);
     
     if (status & STATUS_FOUND) {
         // Determine which lane won
         int lane0_winner = (debug_comparison & 0x01) != 0;
         int lane1_winner = (debug_comparison & 0x02) != 0;
         
         // Extract the 30-byte nonce data (bytes 2-31 of nonce_result)
         // The nonce_result contains [2-byte spacing][30-byte nonce]
         uint8_t winning_nonce_30bytes[30];
         for (int i = 0; i < 30; i++) {
             winning_nonce_30bytes[i] = nonce_bytes[i + 2];
         }
         
         // Determine which core won (Core 0 has priority if both meet target)
         int winning_core = lane0_winner ? 0 : 1;
         const char *strategy = lane0_winner ? "Linear Search" : "Stochastic Chain";
         
         printf("\n--- Winner Information ---\n");
         printf("Winning Core:  %d (%s)\n", winning_core, strategy);
         printf("Winning Nonce: 0x");
         for (int i = 0; i < 30; i++) {
             printf("%02X", winning_nonce_30bytes[i]);
         }
         printf("\n");
         
         printf("\n--- Hash Output ---\n");
         printf("0x");
         for (int i = 0; i < 32; i++) {
             printf("%02X", hash_bytes[i]);
         }
         printf("\n");
         
         printf("\n--- Leading Zero Count (Both Cores) ---\n");
         printf("Target CLZ:     %d\n", target_clz);
         printf("Core 0 CLZ:     %u %s\n", debug_clz0, 
                lane0_winner ? "✓ WINNER" : (debug_clz0 >= target_clz ? "(also met target)" : ""));
         printf("Core 1 CLZ:     %u %s\n", debug_clz1,
                lane1_winner ? "✓ WINNER" : (debug_clz1 >= target_clz ? "(also met target)" : ""));
         
         // Determine winner CLZ
         int winner_clz = lane0_winner ? debug_clz0 : debug_clz1;
         
         if (winner_clz >= target_clz) {
             printf("\n✓✓✓ PASS ✓✓✓\n");
             printf("Valid nonce found (%d leading zeros)\n", winner_clz);
         } else {
             printf("\n✗✗✗ FAIL ✗✗✗\n");
             printf("Hardware error: reported success but CLZ=%d < target=%d\n", 
                    winner_clz, target_clz);
         }
     } else if (status & STATUS_TIMEOUT) {
         printf("\n⚠ TIMEOUT ⚠\n");
         printf("No solution found in %llu iterations\n", (unsigned long long)final_iters);
     }
 
     // Stop
     regs[REG_CONTROL / 4] = 2;
     __sync_synchronize();
     regs[REG_CONTROL / 4] = 0;
 }
 
 int main(int argc, char *argv[]) {
     if (init_hw() < 0) {
         perror("HW Init failed");
         return 1;
     }
     
     int target_clz = 8;
     uint64_t timeout = 0;  // 0 = disabled (no clock cycle limit)
     int input_size = DEFAULT_INPUT_SIZE;
     int debug_enabled = 0;
     uint64_t attempt_limit = 0; // 0 = disabled
     
     /* Parse positional arguments */
     if (argc >= 2) {
         target_clz = atoi(argv[1]);
     }
     if (argc >= 3) {
         timeout = strtoull(argv[2], NULL, 10);
     }
     if (argc >= 4) {
         input_size = atoi(argv[3]);
         if (input_size < 1 || input_size > MAX_INPUT_SIZE) {
             fprintf(stderr, "Error: input_size must be between 1 and %d bytes\n", MAX_INPUT_SIZE);
             return 1;
         }
     }
     if (argc >= 5) {
        attempt_limit = strtoull(argv[4], NULL, 10); 
     }
     
     /* Parse optional flags */
     for (int i = 1; i < argc; i++) {
         if (strcmp(argv[i], "-debug") == 0) {
             debug_enabled = 1;
         }
     }
     
     printf("SHA3 TxPoW CLZ Accelerator Test\n");
     printf("Usage: %s [target_clz] [timeout_cycles] [input_size] [attempt_limit] [-debug]\n", argv[0]);
     printf("  target_clz: Target leading zeros (default: 8)\n");
     printf("  timeout_cycles: Hardware clock cycles, 0=disabled (default: 0)\n");
     printf("  input_size: Input data size in bytes (1-%d, default %d)\n", 
            MAX_INPUT_SIZE, DEFAULT_INPUT_SIZE);
     printf("  attempt_limit: Max number of attempts, 0=disabled (default: 0)\n");
     printf("  -debug: Enable block-by-block debugging output\n");
     
     run_clz_test(target_clz, timeout, attempt_limit, input_size, debug_enabled);
     
     return 0;
 }