#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <time.h>
#include <stdint.h>
int main(void) {
    struct timespec ts;
#ifdef CLOCK_MONOTONIC_RAW
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    uint64_t n = (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
    printf("%llu\n", (unsigned long long)n);
    return 0;
}
