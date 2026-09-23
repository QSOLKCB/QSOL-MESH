// SPDX-License-Identifier: Apache-2.0
#include <cuda_runtime.h>

#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace {
constexpr unsigned int kThreads = 256;
constexpr unsigned long long kSeed = 0x4d4553485f534d4bULL;

__device__ __forceinline__ unsigned long long mix64(unsigned long long x) {
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

__global__ void reduce_chunk(const unsigned long long* ids, unsigned long long count,
                             unsigned long long* partial) {
    unsigned long long offset = static_cast<unsigned long long>(blockIdx.x) * blockDim.x + threadIdx.x;
    const unsigned long long stride = static_cast<unsigned long long>(gridDim.x) * blockDim.x;
    unsigned long long local = 0;
    while (offset < count) {
        local += mix64(ids[offset] ^ kSeed);
        if (count - offset <= stride) break;
        offset += stride;
    }
    atomicAdd(partial, local);
}

struct Resources {
    unsigned long long* host_ids = nullptr;
    unsigned long long* host_partial = nullptr;
    unsigned long long* device_ids = nullptr;
    unsigned long long* device_partial = nullptr;
    cudaStream_t stream = nullptr;
    cudaEvent_t uploaded = nullptr;
    cudaEvent_t executed = nullptr;
    cudaEvent_t downloaded = nullptr;
    ~Resources() {
        if (downloaded) cudaEventDestroy(downloaded);
        if (executed) cudaEventDestroy(executed);
        if (uploaded) cudaEventDestroy(uploaded);
        if (stream) cudaStreamDestroy(stream);
        if (device_partial) cudaFree(device_partial);
        if (device_ids) cudaFree(device_ids);
        if (host_partial) cudaFreeHost(host_partial);
        if (host_ids) cudaFreeHost(host_ids);
    }
};

bool parse_unsigned(const char* value, unsigned long long* output) {
    if (!value || !*value || *value == '-' || *value == '+') return false;
    for (const char* p = value; *p; ++p) if (*p < '0' || *p > '9') return false;
    errno = 0;
    char* end = nullptr;
    *output = std::strtoull(value, &end, 10);
    return errno == 0 && end != value && *end == '\0';
}

int fail(const char* operation, cudaError_t status) {
    std::fprintf(stderr, "mesh-cuda-stream: %s failed: %s\n", operation, cudaGetErrorString(status));
    return 3;
}

int release(Resources& pool) {
    cudaError_t status = cudaEventDestroy(pool.downloaded);
    if (status != cudaSuccess) return fail("cudaEventDestroy(download)", status);
    pool.downloaded = nullptr;
    status = cudaEventDestroy(pool.executed);
    if (status != cudaSuccess) return fail("cudaEventDestroy(execute)", status);
    pool.executed = nullptr;
    status = cudaEventDestroy(pool.uploaded);
    if (status != cudaSuccess) return fail("cudaEventDestroy(upload)", status);
    pool.uploaded = nullptr;
    status = cudaStreamDestroy(pool.stream);
    if (status != cudaSuccess) return fail("cudaStreamDestroy", status);
    pool.stream = nullptr;
    status = cudaFree(pool.device_partial);
    if (status != cudaSuccess) return fail("cudaFree(partial)", status);
    pool.device_partial = nullptr;
    status = cudaFree(pool.device_ids);
    if (status != cudaSuccess) return fail("cudaFree(pool)", status);
    pool.device_ids = nullptr;
    status = cudaFreeHost(pool.host_partial);
    if (status != cudaSuccess) return fail("cudaFreeHost(partial)", status);
    pool.host_partial = nullptr;
    status = cudaFreeHost(pool.host_ids);
    if (status != cudaSuccess) return fail("cudaFreeHost(staging)", status);
    pool.host_ids = nullptr;
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    const char* names[] = {"--items", "--chunk-items", "--pinned-limit-bytes",
                           "--accelerator-limit-bytes", "--device"};
    unsigned long long values[5] = {};
    bool seen[5] = {};
    for (int arg = 1; arg < argc; arg += 2) {
        if (arg + 1 >= argc) {
            std::fprintf(stderr, "mesh-cuda-stream: missing option value\n");
            return 2;
        }
        int field = -1;
        for (int i = 0; i < 5; ++i) if (std::strcmp(argv[arg], names[i]) == 0) field = i;
        if (field < 0 || seen[field] || !parse_unsigned(argv[arg + 1], &values[field])) {
            std::fprintf(stderr, "mesh-cuda-stream: unknown, duplicate, or invalid option\n");
            return 2;
        }
        seen[field] = true;
    }
    for (bool present : seen) if (!present) {
        std::fprintf(stderr, "mesh-cuda-stream: all options are required\n");
        return 2;
    }
    const auto items = values[0];
    const auto requested_chunk = values[1];
    const auto pinned_limit = values[2];
    const auto accelerator_limit = values[3];
    if (!items || !requested_chunk || pinned_limit < 16 || accelerator_limit < 16 ||
        values[4] > static_cast<unsigned long long>(std::numeric_limits<int>::max())) {
        std::fprintf(stderr, "mesh-cuda-stream: invalid chunk, budget, or device\n");
        return 2;
    }
    unsigned long long chunk = items;
    if (chunk > requested_chunk) chunk = requested_chunk;
    if (chunk > (pinned_limit - 8) / 8) chunk = (pinned_limit - 8) / 8;
    if (chunk > (accelerator_limit - 8) / 8) chunk = (accelerator_limit - 8) / 8;
    if (chunk > std::numeric_limits<size_t>::max() / 8) {
        chunk = std::numeric_limits<size_t>::max() / 8;
    }
    if (!chunk) return 2;
    const auto chunks = (items - 1) / chunk + 1;
    if (chunks > std::numeric_limits<unsigned long long>::max() / 3) return 2;
    const auto bytes = static_cast<size_t>(chunk * 8);
    const int device = static_cast<int>(values[4]);

    cudaError_t status = cudaSetDevice(device);
    if (status != cudaSuccess) return fail("cudaSetDevice", status);
    cudaDeviceProp properties{};
    status = cudaGetDeviceProperties(&properties, device);
    if (status != cudaSuccess) return fail("cudaGetDeviceProperties", status);
    if (properties.multiProcessorCount <= 0) return 3;
    int runtime = 0, driver = 0;
    status = cudaRuntimeGetVersion(&runtime);
    if (status != cudaSuccess) return fail("cudaRuntimeGetVersion", status);
    status = cudaDriverGetVersion(&driver);
    if (status != cudaSuccess) return fail("cudaDriverGetVersion", status);

    Resources pool;
    status = cudaHostAlloc(reinterpret_cast<void**>(&pool.host_ids), bytes, cudaHostAllocDefault);
    if (status != cudaSuccess) return fail("cudaHostAlloc(staging)", status);
    status = cudaHostAlloc(reinterpret_cast<void**>(&pool.host_partial), 8, cudaHostAllocDefault);
    if (status != cudaSuccess) return fail("cudaHostAlloc(partial)", status);
    status = cudaMalloc(reinterpret_cast<void**>(&pool.device_ids), bytes);
    if (status != cudaSuccess) return fail("cudaMalloc(pool)", status);
    status = cudaMalloc(reinterpret_cast<void**>(&pool.device_partial), 8);
    if (status != cudaSuccess) return fail("cudaMalloc(partial)", status);
    status = cudaStreamCreateWithFlags(&pool.stream, cudaStreamNonBlocking);
    if (status != cudaSuccess) return fail("cudaStreamCreate", status);
    status = cudaEventCreateWithFlags(&pool.uploaded, cudaEventDisableTiming);
    if (status != cudaSuccess) return fail("cudaEventCreate(upload)", status);
    status = cudaEventCreateWithFlags(&pool.executed, cudaEventDisableTiming);
    if (status != cudaSuccess) return fail("cudaEventCreate(execute)", status);
    status = cudaEventCreateWithFlags(&pool.downloaded, cudaEventDisableTiming);
    if (status != cudaSuccess) return fail("cudaEventCreate(download)", status);

    unsigned long long checksum = 0;
    unsigned long long offset = 0;
    const auto occupancy = static_cast<unsigned long long>(properties.multiProcessorCount) * 4;
    for (unsigned long long index = 0; index < chunks; ++index) {
        const auto count = items - offset < chunk ? items - offset : chunk;
        const auto transfer_bytes = static_cast<size_t>(count * 8);
        for (unsigned long long i = 0; i < count; ++i) pool.host_ids[i] = offset + i;
        status = cudaMemcpyAsync(pool.device_ids, pool.host_ids, transfer_bytes,
                                 cudaMemcpyHostToDevice, pool.stream);
        if (status != cudaSuccess) return fail("cudaMemcpyAsync(upload)", status);
        status = cudaEventRecord(pool.uploaded, pool.stream);
        if (status != cudaSuccess) return fail("cudaEventRecord(upload)", status);
        status = cudaMemsetAsync(pool.device_partial, 0, 8, pool.stream);
        if (status != cudaSuccess) return fail("cudaMemsetAsync(partial)", status);
        auto blocks = (count - 1) / kThreads + 1;
        if (blocks > occupancy) blocks = occupancy;
        reduce_chunk<<<static_cast<unsigned int>(blocks), kThreads, 0, pool.stream>>>(
            pool.device_ids, count, pool.device_partial);
        status = cudaGetLastError();
        if (status != cudaSuccess) return fail("kernel launch", status);
        status = cudaEventRecord(pool.executed, pool.stream);
        if (status != cudaSuccess) return fail("cudaEventRecord(execute)", status);
        status = cudaMemcpyAsync(pool.host_partial, pool.device_partial, 8,
                                 cudaMemcpyDeviceToHost, pool.stream);
        if (status != cudaSuccess) return fail("cudaMemcpyAsync(download)", status);
        status = cudaEventRecord(pool.downloaded, pool.stream);
        if (status != cudaSuccess) return fail("cudaEventRecord(download)", status);
        status = cudaEventSynchronize(pool.downloaded);
        if (status != cudaSuccess) return fail("cudaEventSynchronize(download)", status);
        status = cudaEventQuery(pool.uploaded);
        if (status != cudaSuccess) return fail("cudaEventQuery(upload)", status);
        status = cudaEventQuery(pool.executed);
        if (status != cudaSuccess) return fail("cudaEventQuery(execute)", status);
        checksum += *pool.host_partial;
        offset += count;
    }
    if (offset != items) return 3;
    const int teardown = release(pool);
    if (teardown != 0) return teardown;
    std::printf(
        "qsol.mesh.cuda-stream-worker.v1\titems=%llu\tchunk_items=%llu\tchunks=%llu"
        "\tchecksum=%016llx\tdevice=%d\tcompute_major=%d\tcompute_minor=%d"
        "\tcuda_runtime=%d\tcuda_driver=%d\thost_pinned_peak_bytes=%llu"
        "\taccelerator_peak_bytes=%llu\tpinned_staging_allocations=1"
        "\tpinned_partial_allocations=1\tdevice_pool_allocations=1"
        "\tdevice_partial_allocations=1\tevent_records=%llu\tpartial_bytes=8\n",
        items, chunk, chunks, checksum, device, properties.major, properties.minor,
        runtime, driver, chunk * 8 + 8, chunk * 8 + 8, chunks * 3);
    return 0;
}
