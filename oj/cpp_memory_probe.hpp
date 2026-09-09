// Linux g++/clang++ instrumentation: only failed new allocations invoke this hook.
// A manual throw std::bad_alloc() does not produce evidence. A submission that
// replaces new/new_handler can disable the probe; this is not a hostile-code sandbox.
#pragma once

#include <atomic>
#include <fcntl.h>
#include <new>
#include <unistd.h>

namespace {
std::atomic<int> oj_memory_signal_fd{-1};

void oj_allocation_failed() {
    const int descriptor = oj_memory_signal_fd.exchange(-1);
    if (descriptor >= 0) {
        const char marker[] = "OOM\n";
        (void)::write(descriptor, marker, sizeof(marker) - 1);
        ::close(descriptor);
    }
    throw std::bad_alloc();
}

struct OjMemoryProbe {
    OjMemoryProbe() {
        oj_memory_signal_fd = ::open(
            OJ_MEMORY_SIGNAL_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        std::set_new_handler(oj_allocation_failed);
    }
    ~OjMemoryProbe() {
        const int descriptor = oj_memory_signal_fd.exchange(-1);
        if (descriptor >= 0) {
            ::close(descriptor);
        }
    }
};

OjMemoryProbe oj_memory_probe;
}  // namespace
