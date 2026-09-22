// SPDX-License-Identifier: Apache-2.0
#include <cuda_runtime.h>

#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace {

constexpr unsigned long long kSmokeSeed = 0x4d4553485f534d4bULL;
constexpr unsigned int kThreadsPerBlock = 256;

__device__ __forceinline__ unsigned long long mix64(unsigned long long x) {
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

__global__ void smoke_kernel(
    unsigned long long start,
    unsigned long long items,
    unsigned long long* checksum
) {
    const unsigned long long tid =
        static_cast<unsigned long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const unsigned long long stride =
        static_cast<unsigned long long>(gridDim.x) * blockDim.x;

    unsigned long long local = 0;
    unsigned long long offset = tid;
    while (offset < items) {
        const unsigned long long id = start + offset;
        local += mix64(id ^ kSmokeSeed);
        const unsigned long long remaining = items - offset;
        if (remaining <= stride) {
            break;
        }
        offset += stride;
    }
    atomicAdd(checksum, local);
}

bool parse_u64(const char* value, unsigned long long* output) {
    if (value == nullptr || value[0] == '\0') {
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const unsigned long long parsed = std::strtoull(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0') {
        return false;
    }
    *output = parsed;
    return true;
}

bool parse_i32(const char* value, int* output) {
    if (value == nullptr || value[0] == '\0') {
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const long parsed = std::strtol(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0'
        || parsed < std::numeric_limits<int>::min()
        || parsed > std::numeric_limits<int>::max()) {
        return false;
    }
    *output = static_cast<int>(parsed);
    return true;
}

int fail_cuda(const char* operation, cudaError_t error) {
    std::fprintf(
        stderr,
        "mesh-cuda-smoke: %s failed: %s\n",
        operation,
        cudaGetErrorString(error)
    );
    return 3;
}

}  // namespace

int main(int argc, char** argv) {
    unsigned long long start = 0;
    unsigned long long items = 0;
    int device_ordinal = 0;
    bool saw_start = false;
    bool saw_items = false;
    bool saw_device = false;

    for (int index = 1; index < argc; ++index) {
        if (std::strcmp(argv[index], "--start") == 0) {
            if (saw_start || index + 1 >= argc || !parse_u64(argv[index + 1], &start)) {
                std::fprintf(stderr, "mesh-cuda-smoke: invalid --start\n");
                return 2;
            }
            saw_start = true;
            ++index;
        } else if (std::strcmp(argv[index], "--items") == 0) {
            if (saw_items || index + 1 >= argc || !parse_u64(argv[index + 1], &items)) {
                std::fprintf(stderr, "mesh-cuda-smoke: invalid --items\n");
                return 2;
            }
            saw_items = true;
            ++index;
        } else if (std::strcmp(argv[index], "--device") == 0) {
            if (saw_device || index + 1 >= argc || !parse_i32(argv[index + 1], &device_ordinal)) {
                std::fprintf(stderr, "mesh-cuda-smoke: invalid --device\n");
                return 2;
            }
            saw_device = true;
            ++index;
        } else {
            std::fprintf(stderr, "mesh-cuda-smoke: unsupported argument: %s\n", argv[index]);
            return 2;
        }
    }

    if (!saw_items || items == 0) {
        std::fprintf(stderr, "mesh-cuda-smoke: --items must be greater than zero\n");
        return 2;
    }
    if (start > std::numeric_limits<unsigned long long>::max() - items) {
        std::fprintf(stderr, "mesh-cuda-smoke: requested logical range overflows u64\n");
        return 2;
    }
    if (device_ordinal < 0) {
        std::fprintf(stderr, "mesh-cuda-smoke: --device must be non-negative\n");
        return 2;
    }

    cudaError_t status = cudaSetDevice(device_ordinal);
    if (status != cudaSuccess) {
        return fail_cuda("cudaSetDevice", status);
    }

    cudaDeviceProp properties{};
    status = cudaGetDeviceProperties(&properties, device_ordinal);
    if (status != cudaSuccess) {
        return fail_cuda("cudaGetDeviceProperties", status);
    }
    if (properties.multiProcessorCount <= 0) {
        std::fprintf(stderr, "mesh-cuda-smoke: device reports no multiprocessors\n");
        return 3;
    }

    int runtime_version = 0;
    status = cudaRuntimeGetVersion(&runtime_version);
    if (status != cudaSuccess) {
        return fail_cuda("cudaRuntimeGetVersion", status);
    }

    int driver_version = 0;
    status = cudaDriverGetVersion(&driver_version);
    if (status != cudaSuccess) {
        return fail_cuda("cudaDriverGetVersion", status);
    }

    const unsigned long long required_blocks =
        1ULL + (items - 1ULL) / static_cast<unsigned long long>(kThreadsPerBlock);
    const unsigned long long occupancy_blocks =
        static_cast<unsigned long long>(properties.multiProcessorCount) * 4ULL;
    unsigned long long selected_blocks =
        required_blocks < occupancy_blocks ? required_blocks : occupancy_blocks;
    if (selected_blocks == 0) {
        selected_blocks = 1;
    }
    if (selected_blocks > std::numeric_limits<unsigned int>::max()) {
        selected_blocks = std::numeric_limits<unsigned int>::max();
    }
    const unsigned int blocks = static_cast<unsigned int>(selected_blocks);

    unsigned long long* device_checksum = nullptr;
    status = cudaMalloc(reinterpret_cast<void**>(&device_checksum), sizeof(unsigned long long));
    if (status != cudaSuccess) {
        return fail_cuda("cudaMalloc", status);
    }

    status = cudaMemset(device_checksum, 0, sizeof(unsigned long long));
    if (status != cudaSuccess) {
        cudaFree(device_checksum);
        return fail_cuda("cudaMemset", status);
    }

    smoke_kernel<<<blocks, kThreadsPerBlock>>>(start, items, device_checksum);
    status = cudaGetLastError();
    if (status != cudaSuccess) {
        cudaFree(device_checksum);
        return fail_cuda("kernel launch", status);
    }

    status = cudaDeviceSynchronize();
    if (status != cudaSuccess) {
        cudaFree(device_checksum);
        return fail_cuda("cudaDeviceSynchronize", status);
    }

    unsigned long long checksum = 0;
    status = cudaMemcpy(
        &checksum,
        device_checksum,
        sizeof(unsigned long long),
        cudaMemcpyDeviceToHost
    );
    if (status != cudaSuccess) {
        cudaFree(device_checksum);
        return fail_cuda("cudaMemcpy", status);
    }

    status = cudaFree(device_checksum);
    if (status != cudaSuccess) {
        return fail_cuda("cudaFree", status);
    }

    if (saw_start) {
        std::printf(
            "qsol.mesh.cuda-smoke-range-worker.v1\tstart=%llu\titems=%llu\tchecksum=%016llx\tblocks=%u\tthreads_per_block=%u\tdevice=%d\tcompute_major=%d\tcompute_minor=%d\tcuda_runtime=%d\tcuda_driver=%d\n",
            start,
            items,
            checksum,
            blocks,
            kThreadsPerBlock,
            device_ordinal,
            properties.major,
            properties.minor,
            runtime_version,
            driver_version
        );
    } else {
        std::printf(
            "qsol.mesh.cuda-smoke-worker.v1\titems=%llu\tchecksum=%016llx\tblocks=%u\tthreads_per_block=%u\tdevice=%d\tcompute_major=%d\tcompute_minor=%d\tcuda_runtime=%d\tcuda_driver=%d\n",
            items,
            checksum,
            blocks,
            kThreadsPerBlock,
            device_ordinal,
            properties.major,
            properties.minor,
            runtime_version,
            driver_version
        );
    }
    return 0;
}
