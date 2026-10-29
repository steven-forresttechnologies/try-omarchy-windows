/* Native Windows host-import and Linux guest transfer/readback acceptance. */
#ifdef _WIN32
#define VK_USE_PLATFORM_WIN32_KHR
#include <windows.h>
#endif
#include <vulkan/vulkan.h>

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(call) do { \
    VkResult result = (call); \
    if (result != VK_SUCCESS) { \
        fprintf(stderr, "%s failed: %d\n", #call, result); \
        goto cleanup; \
    } \
} while (0)

static uint32_t memory_type(const VkPhysicalDeviceMemoryProperties *properties,
                            uint32_t bits, VkMemoryPropertyFlags flags)
{
    for (uint32_t i = 0; i < properties->memoryTypeCount; i++) {
        if ((bits & (1u << i)) &&
            (properties->memoryTypes[i].propertyFlags & flags) == flags)
            return i;
    }
    return UINT32_MAX;
}

int main(void)
{
    int status = 1;
    const VkDeviceSize bytes = 256 * 256 * 4;
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkBuffer source = VK_NULL_HANDLE, readback = VK_NULL_HANDLE;
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory source_memory = VK_NULL_HANDLE;
    VkDeviceMemory readback_memory = VK_NULL_HANDLE, image_memory = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
#ifdef _WIN32
    HANDLE section = NULL;
#endif
    unsigned char *input = NULL;
    void *output = NULL;
    VkApplicationInfo application = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "Try Omarchy host import acceptance",
        .apiVersion = VK_API_VERSION_1_2,
    };
    VkInstanceCreateInfo instance_info = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &application,
    };
    CHECK(vkCreateInstance(&instance_info, NULL, &instance));
    uint32_t count = 8;
    VkPhysicalDevice physical[8];
    CHECK(vkEnumeratePhysicalDevices(instance, &count, physical));
    if (!count) goto cleanup;
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(physical[0], &properties);
    printf("Device: %s\n", properties.deviceName);
    if (properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU) {
        fprintf(stderr, "CPU Vulkan device cannot satisfy GPU acceptance\n");
        goto cleanup;
    }
    VkPhysicalDeviceMemoryProperties memory;
    vkGetPhysicalDeviceMemoryProperties(physical[0], &memory);
    VkQueueFamilyProperties families[32];
    uint32_t family_count = 32, family = UINT32_MAX;
    vkGetPhysicalDeviceQueueFamilyProperties(physical[0], &family_count, families);
    for (uint32_t i = 0; i < family_count; i++) {
        if (families[i].queueFlags & VK_QUEUE_TRANSFER_BIT) {
            family = i;
            break;
        }
    }
    if (family == UINT32_MAX) goto cleanup;
    float priority = 1;
    VkDeviceQueueCreateInfo queue_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1,
        .pQueuePriorities = &priority,
    };
#ifdef _WIN32
    const char *extension = VK_EXT_EXTERNAL_MEMORY_HOST_EXTENSION_NAME;
#endif
    VkDeviceCreateInfo device_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_info,
#ifdef _WIN32
        .enabledExtensionCount = 1, .ppEnabledExtensionNames = &extension,
#endif
    };
    CHECK(vkCreateDevice(physical[0], &device_info, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
#ifdef _WIN32
    VkExternalMemoryBufferCreateInfo external = {
        .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,
        .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT,
    };
#endif
    VkBufferCreateInfo buffer_info = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
#ifdef _WIN32
        .pNext = &external,
#endif
        .size = bytes, .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
    };
    CHECK(vkCreateBuffer(device, &buffer_info, NULL, &source));
    VkMemoryRequirements requirements;
    vkGetBufferMemoryRequirements(device, source, &requirements);
#ifdef _WIN32
    section = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
        (DWORD)(requirements.size >> 32), (DWORD)requirements.size, NULL);
    if (!section) goto cleanup;
    input = MapViewOfFile(section, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0,
                          (SIZE_T)requirements.size);
    if (!input) goto cleanup;
    PFN_vkGetMemoryHostPointerPropertiesEXT host_properties =
        (PFN_vkGetMemoryHostPointerPropertiesEXT)vkGetDeviceProcAddr(
            device, "vkGetMemoryHostPointerPropertiesEXT");
    if (!host_properties) goto cleanup;
    VkMemoryHostPointerPropertiesEXT pointer = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_HOST_POINTER_PROPERTIES_EXT,
    };
    CHECK(host_properties(device, VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT,
                           input, &pointer));
    uint32_t type = memory_type(&memory, requirements.memoryTypeBits & pointer.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    printf("Host buffer mask: 0x%x; pointer mask: 0x%x\n",
           requirements.memoryTypeBits, pointer.memoryTypeBits);
    if (type == UINT32_MAX) goto cleanup;
    VkImportMemoryHostPointerInfoEXT import_info = {
        .sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_HOST_POINTER_INFO_EXT,
        .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT,
        .pHostPointer = input,
    };
#else
    uint32_t type = memory_type(&memory, requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    printf("Guest staging buffer mask: 0x%x\n", requirements.memoryTypeBits);
    if (type == UINT32_MAX) goto cleanup;
#endif
    VkMemoryAllocateInfo allocation = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
#ifdef _WIN32
        .pNext = &import_info,
#endif
        .allocationSize = requirements.size, .memoryTypeIndex = type,
    };
    CHECK(vkAllocateMemory(device, &allocation, NULL, &source_memory));
    CHECK(vkBindBufferMemory(device, source, source_memory, 0));
#ifndef _WIN32
    CHECK(vkMapMemory(device, source_memory, 0, bytes, 0, (void **)&input));
#endif
    for (VkDeviceSize i = 0; i < bytes; i++) input[i] = (unsigned char)((i * 131 + i / 257) ^ 0xa5);

    buffer_info.pNext = NULL;
    buffer_info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    CHECK(vkCreateBuffer(device, &buffer_info, NULL, &readback));
    vkGetBufferMemoryRequirements(device, readback, &requirements);
    type = memory_type(&memory, requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (type == UINT32_MAX) goto cleanup;
    allocation.pNext = NULL;
    allocation.allocationSize = requirements.size;
    allocation.memoryTypeIndex = type;
    CHECK(vkAllocateMemory(device, &allocation, NULL, &readback_memory));
    CHECK(vkBindBufferMemory(device, readback, readback_memory, 0));
    CHECK(vkMapMemory(device, readback_memory, 0, bytes, 0, &output));
    memset(output, 0, (size_t)bytes);

    VkImageCreateInfo image_info = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {256, 256, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
    };
    CHECK(vkCreateImage(device, &image_info, NULL, &image));
    vkGetImageMemoryRequirements(device, image, &requirements);
    type = memory_type(&memory, requirements.memoryTypeBits, 0);
    if (type == UINT32_MAX) goto cleanup;
    allocation.allocationSize = requirements.size;
    allocation.memoryTypeIndex = type;
    CHECK(vkAllocateMemory(device, &allocation, NULL, &image_memory));
    CHECK(vkBindImageMemory(device, image, image_memory, 0));
    VkCommandPoolCreateInfo pool_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family,
    };
    CHECK(vkCreateCommandPool(device, &pool_info, NULL, &pool));
    VkCommandBufferAllocateInfo command_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1,
    };
    VkCommandBuffer command;
    CHECK(vkAllocateCommandBuffers(device, &command_info, &command));
    VkCommandBufferBeginInfo begin = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
    };
    CHECK(vkBeginCommandBuffer(command, &begin));
    VkImageMemoryBarrier barrier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = image, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
    };
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, NULL, 0, NULL, 1, &barrier);
    VkBufferImageCopy copy = {
        .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {256, 256, 1},
    };
    vkCmdCopyBufferToImage(command, source, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, NULL, 0, NULL, 1, &barrier);
    vkCmdCopyImageToBuffer(command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, readback, 1, &copy);
    VkMemoryBarrier host_barrier = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
    };
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                         0, 1, &host_barrier, 0, NULL, 0, NULL);
    CHECK(vkEndCommandBuffer(command));
    VkFenceCreateInfo fence_info = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    CHECK(vkCreateFence(device, &fence_info, NULL, &fence));
    VkSubmitInfo submit = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &command,
    };
    CHECK(vkQueueSubmit(queue, 1, &submit, fence));
    CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, 5000000000ull));
    if (memcmp(input, output, (size_t)bytes)) {
        fprintf(stderr, "GPU readback differs from imported host bytes\n");
        goto cleanup;
    }
    printf("HOST_IMPORT_IMAGE_READBACK_OK bytes=%llu\n", (unsigned long long)bytes);
    status = 0;

cleanup:
    if (device) {
        /* The process also has an external timeout for a broken driver. */
        vkDeviceWaitIdle(device);
        if (fence) vkDestroyFence(device, fence, NULL);
        if (pool) vkDestroyCommandPool(device, pool, NULL);
        if (image) vkDestroyImage(device, image, NULL);
        if (image_memory) vkFreeMemory(device, image_memory, NULL);
        if (source) vkDestroyBuffer(device, source, NULL);
#ifndef _WIN32
        if (input) vkUnmapMemory(device, source_memory);
#endif
        if (source_memory) vkFreeMemory(device, source_memory, NULL);
        if (readback) vkDestroyBuffer(device, readback, NULL);
        if (output) vkUnmapMemory(device, readback_memory);
        if (readback_memory) vkFreeMemory(device, readback_memory, NULL);
        vkDestroyDevice(device, NULL);
    }
#ifdef _WIN32
    if (input) UnmapViewOfFile(input);
    if (section) CloseHandle(section);
#endif
    if (instance) vkDestroyInstance(instance, NULL);
    return status;
}
