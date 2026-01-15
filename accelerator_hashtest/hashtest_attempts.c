/**
 * SHA3 TxPoW CLZ Accelerator - Performance Benchmark
 * 
 * This test runs on the RISC-V SoC and benchmarks the FPGA accelerator
 * across varying attempt limits (mining difficulty simulation).
 * 
 * Compile: ./compile_hashtest_perf.sh
 * Run on hardware: ./hashtest_perf [input_size]
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
#define DEFAULT_INPUT_SIZE   1000    // Default input header size if not specified
#define MAX_INPUT_SIZE      2176     // Maximum: 16 blocks × 136 bytes/block
#define REPEATS_PER_TEST    10      // Number of times to repeat each test for averaging
#define BENCHMARK_OUTPUT "hashtest_attempts_results.csv"

/* Register Offsets */
#define REG_CONTROL          0x000
#define REG_STATUS           0x004
#define REG_NONCE_RESULT     0x008
#define REG_HASH_RESULT      0x028
#define REG_ITERATION_COUNT  0x048
#define REG_TARGET_CLZ       0x050
#define REG_TIMEOUT          0x0E0
#define REG_ATTEMPT_LIMIT    0x0E8
#define REG_INPUT_LEN        0x0F0
#define REG_HEADER_DATA_LOW  0x0F4
#define REG_HEADER_DATA_HIGH 0x0F8
#define REG_HEADER_ADDR      0x0FC
#define REG_HEADER_WE        0x100

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
    size_t num_words = (length + 7) / 8;
    
    for (size_t word_idx = 0; word_idx < num_words; word_idx++) {
        uint64_t word = 0;
        for (int byte_offset = 0; byte_offset < 8; byte_offset++) {
            size_t global_byte_idx = (word_idx * 8) + byte_offset;
            if (global_byte_idx < length) {
                word |= ((uint64_t)data[global_byte_idx]) << (byte_offset * 8);
            }
        }
        
        uint32_t low  = (uint32_t)(word & 0xFFFFFFFF);
        uint32_t high = (uint32_t)(word >> 32);
        
        regs[REG_HEADER_ADDR / 4]      = (uint32_t)word_idx;
        regs[REG_HEADER_DATA_LOW / 4]  = low;
        regs[REG_HEADER_DATA_HIGH / 4] = high;
        
        __sync_synchronize();
        regs[REG_HEADER_WE / 4] = 1;
        
        // Small delay
        for (volatile int delay = 0; delay < 20; delay++);
        
        regs[REG_HEADER_WE / 4] = 0;
        __sync_synchronize();
    }
}

void generate_test_header(uint8_t *buffer, size_t length) {
    // Repeating pattern to fill data
    uint8_t pattern[] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
    for (size_t i = 0; i < length; i++) {
        buffer[i] = pattern[i % 8];
    }
    
    // Set Header Structure
    buffer[0] = 1;   // Scale
    buffer[1] = 32;  // Length
    
    // Clear Nonce Field (bytes 2-33) to ZERO
    for (int i = 2; i < 34; i++) {
        buffer[i] = 0;
    }
}

// Struct to hold result of one run
typedef struct {
    uint64_t cpu_cycles;
    double time_sec;
    uint64_t hashes_performed;
} RunResult;

RunResult run_single_test(int target_clz, uint64_t attempt_limit, int input_size) {
    RunResult result = {0};
    
    // 1. Reset
    regs[REG_CONTROL / 4] = 2; // Stop
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;
    
    // 2. Configure Registers
    // Set Impossible Target CLZ to force running until attempt_limit
    regs[REG_TARGET_CLZ / 4] = target_clz; 
    regs[REG_INPUT_LEN / 4]  = input_size;
    regs[REG_TIMEOUT / 4]     = 0; // Disable timeout by cycles
    regs[REG_TIMEOUT / 4 + 1] = 0;
    
    regs[REG_ATTEMPT_LIMIT / 4]     = (uint32_t)(attempt_limit >> 32);
    regs[REG_ATTEMPT_LIMIT / 4 + 1] = (uint32_t)(attempt_limit & 0xFFFFFFFF);
    
    __sync_synchronize();

    // 3. Start Timing
    uint64_t start_cycles = read_cycles();
    struct timespec start_time, end_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);
    
    // 4. Start Accelerator
    regs[REG_CONTROL / 4] = 1;
    __sync_synchronize();

    // 5. Wait for Completion
    struct timespec wait_start, wait_current;
    clock_gettime(CLOCK_MONOTONIC, &wait_start);
    
    while (1) {
        uint32_t status = regs[REG_STATUS / 4];
        
        // Exit if:
        // - Found solution
        // - Hardware Timeout (cycle usage)
        // - NOT Running (Idle) -> This covers "Attempt Limit Reached" if it simply stops
        if ((status & STATUS_FOUND) || (status & STATUS_TIMEOUT) || !(status & STATUS_RUNNING)) {
            break; 
        }
        
        // Software safety timeout/debug (check elapsed time)
        // 100M attempts @ ~1MH/s takes ~100s. Set limit to 1000s (over 16 mins) to be safe for larger tests.
        clock_gettime(CLOCK_MONOTONIC, &wait_current);
        double elapsed = (wait_current.tv_sec - wait_start.tv_sec) + 
                         (wait_current.tv_nsec - wait_start.tv_nsec) / 1e9;
                         
        if (elapsed > 1000.0) {
            printf("\n[Error] Software timeout (>1000s)! Status: 0x%08X (Running=%d)\n", 
                   status, (status & STATUS_RUNNING) ? 1 : 0);
             // Read current iterations to see if it's moving
            uint32_t h = regs[(REG_ITERATION_COUNT / 4)];
            uint32_t l  = regs[(REG_ITERATION_COUNT / 4) + 1];
            uint64_t cur = ((uint64_t)h << 32) | l;
            printf("Current Iterations: %llu / %llu\n", (unsigned long long)cur, (unsigned long long)attempt_limit);
            break;
        }

        // Minimal sleep to avoid bus contention
        usleep(1000); 
    }

    // 6. Stop Timing
    uint64_t end_cycles = read_cycles();
    clock_gettime(CLOCK_MONOTONIC, &end_time);
    
    result.cpu_cycles = end_cycles - start_cycles;
    result.time_sec = (end_time.tv_sec - start_time.tv_sec) + 
                      (end_time.tv_nsec - start_time.tv_nsec) / 1e9;
    
    // 7. Read actual iterations performed
    uint32_t high = regs[(REG_ITERATION_COUNT / 4)];
    uint32_t low  = regs[(REG_ITERATION_COUNT / 4) + 1];
    result.hashes_performed = ((uint64_t)high << 32) | low;

    // 8. Stop
    regs[REG_CONTROL / 4] = 2; 
    __sync_synchronize();
    regs[REG_CONTROL / 4] = 0;

    return result;
}


// Calculate blocks 
int calc_blocks(int input_size) {
    return (input_size + 135) / 136;
}

int main(int argc, char *argv[]) {
    if (init_hw() < 0) {
        perror("HW Init failed");
        return 1;
    }

    int input_size = DEFAULT_INPUT_SIZE;
    if (argc >= 2) {
        input_size = atoi(argv[1]);
        if (input_size < 1 || input_size > MAX_INPUT_SIZE) {
            fprintf(stderr, "Error: input_size must be 1-%d\n", MAX_INPUT_SIZE);
            return 1;
        }
    }
    
    int num_blocks = calc_blocks(input_size);

    printf("=== CLZ Accelerator Attempts Benchmark ===\n");
    printf("Input Size: %d bytes (%d blocks)\n", input_size, num_blocks);
    printf("Output: %s\n", BENCHMARK_OUTPUT);
    printf("Target CLZ: 255 (Impossible) to ensure full run\n");
    printf("----------------------------------------------------------------\n");
    
    FILE *fp = fopen(BENCHMARK_OUTPUT, "w");
    if (!fp) {
        perror("Failed to open output file");
        return 1;
    }
    
    // CSV Header (Standardized)
    fprintf(fp, "Attempts,Input Size,Blocks,AvgCpuCycles,AvgTime (s),AvgHashRate (MH/s),AvgCyclesPerHash\n");
    printf("%-15s %-12s %-15s %-15s %-15s\n", 
           "Attempts", "Time(s)", "MH/s", "Cyc/Hash", "Avg Cycles");

    // Setup Fixed Header Data once
    uint8_t header_data[MAX_INPUT_SIZE];
    generate_test_header(header_data, input_size);
    write_header_data(header_data, input_size);

    // Iteration steps: 10, 100, 1000 ... 100,000,000
    uint64_t attempts_steps[] = {
        10, 
        100, 
        1000, 
        10000, 
        100000, 
        1000000, 
        10000000, 
        100000000 
    };
    int num_steps = sizeof(attempts_steps) / sizeof(attempts_steps[0]);

    for (int s = 0; s < num_steps; s++) {
        uint64_t current_attempts = attempts_steps[s];
        
        double total_time = 0;
        uint64_t total_cycles = 0;
        uint64_t total_hashes = 0;
        
        // Warmup / Consistency Repeats
        for (int r = 0; r < REPEATS_PER_TEST; r++) {
            RunResult res = run_single_test(255, current_attempts, input_size);
            total_time += res.time_sec;
            total_cycles += res.cpu_cycles;
            total_hashes += res.hashes_performed;
            
            // Progress indicator dot
            printf("."); 
            fflush(stdout);
        }
        
        // Averages
        double avg_time = total_time / REPEATS_PER_TEST;
        uint64_t avg_cycles = total_cycles / REPEATS_PER_TEST;
        double mh_s = 0;
        double cycles_per_hash = 0;
        
        // Calculate metrics based on actual hashes performed (should match attempts)
        // Note: use total_hashes / REPEATS for avg hashes, usually equals current_attempts
        double avg_hashes = (double)total_hashes / REPEATS_PER_TEST;
        
        if (avg_time > 0) {
            mh_s = (avg_hashes / avg_time) / 1e6;
        }
        if (avg_hashes > 0) {
            cycles_per_hash = (double)avg_cycles / avg_hashes;
        }

        // CSV Output (Standardized)
        fprintf(fp, "%llu,%d,%d,%llu,%.6f,%.4f,%.2f\n", 
                (unsigned long long)current_attempts, 
                input_size,
                num_blocks, 
                (unsigned long long)avg_cycles, 
                avg_time, 
                mh_s, 
                cycles_per_hash);
        
        // Console Output (overwrite dots)
        printf("\r%-15llu %-12.6f %-15.4f %-15.2f %-15llu\n", 
               (unsigned long long)current_attempts, 
               avg_time, 
               mh_s, 
               cycles_per_hash, 
               (unsigned long long)avg_cycles);
               
        fflush(fp);
    }
    
    fclose(fp);
    printf("----------------------------------------------------------------\n");
    printf("Benchmark Complete. Results saved to %s\n", BENCHMARK_OUTPUT);
    
    return 0;
}
