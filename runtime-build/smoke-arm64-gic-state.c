/* Native ARM64 WHP API probe. Creates only a disposable, unrun partition.
 * Same-partition get/set success is not migration or saved-session support.
 */
#include <windows.h>
#include <winhvplatform.h>
#include <stdio.h>
#include <string.h>

#define CHECK(call) do { HRESULT hr = (call); \
    printf("%s: 0x%08lx\n", #call, (unsigned long)hr); \
    if (FAILED(hr)) goto cleanup; } while (0)

int main(void)
{
    int status = 1;
    WHV_PARTITION_HANDLE partition = NULL;
    WHV_PARTITION_PROPERTY property = {0};
    void *buffer = NULL;
    CHECK(WHvCreatePartition(&partition));
    property.ProcessorCount = 1;
    CHECK(WHvSetPartitionProperty(partition, WHvPartitionPropertyCodeProcessorCount,
                                  &property, sizeof(property)));
    memset(&property, 0, sizeof(property));
    property.Arm64IcParameters.EmulationMode = WHvArm64IcEmulationModeGicV3;
    property.Arm64IcParameters.GicV3Parameters.GicdBaseAddress = 0x08000000;
    property.Arm64IcParameters.GicV3Parameters.GitsTranslaterBaseAddress = 0x08080000;
    property.Arm64IcParameters.GicV3Parameters.GicPpiPerformanceMonitorsInterrupt = 23;
    property.Arm64IcParameters.GicV3Parameters.GicPpiOverflowInterruptFromCntv = 27;
    CHECK(WHvSetPartitionProperty(partition, WHvPartitionPropertyCodeArm64IcParameters,
                                  &property, sizeof(property)));
    CHECK(WHvSetupPartition(partition));
    CHECK(WHvCreateVirtualProcessor(partition, 0, 0));
    WHV_REGISTER_NAME name = WHvArm64RegisterGicrBaseGpa;
    WHV_REGISTER_VALUE value = {.Reg64 = 0x080A0000};
    CHECK(WHvSetVirtualProcessorRegisters(partition, 0, &name, 1, &value));
    const WHV_VIRTUAL_PROCESSOR_STATE_TYPE types[] = {
        WHvVirtualProcessorStateTypeInterruptControllerState,
        WHvVirtualProcessorStateTypeGlobalInterruptState,
    };
    for (unsigned i = 0; i < sizeof(types) / sizeof(types[0]); i++) {
        UINT32 needed = 0, written = 0;
        UINT32 vp = (types[i] & WHV_VIRTUAL_PROCESSOR_STATE_TYPE_ANY_VP) ? WHV_ANY_VP : 0;
        HRESULT hr = WHvGetVirtualProcessorState(partition, vp, types[i], NULL, 0, &needed);
        printf("SIZE type=0x%08x hr=0x%08lx bytes=%u\n", types[i], (unsigned long)hr, needed);
        if (!needed || needed > (1u << 20)) goto cleanup;
        buffer = VirtualAlloc(NULL, needed, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (!buffer) goto cleanup;
        CHECK(WHvGetVirtualProcessorState(partition, vp, types[i], buffer, needed, &written));
        printf("GET type=0x%08x bytes=%u\n", types[i], written);
        CHECK(WHvSetVirtualProcessorState(partition, vp, types[i], buffer, written));
        VirtualFree(buffer, 0, MEM_RELEASE);
        buffer = NULL;
    }
    puts("GIC_SAME_PARTITION_GET_SET_OK");
    status = 0;
cleanup:
    if (buffer) VirtualFree(buffer, 0, MEM_RELEASE);
    if (partition) WHvDeletePartition(partition);
    return status;
}
