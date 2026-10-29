#!/usr/bin/env python3
"""Exercise the real Windows resource shims with mocked Vulkan driver calls."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
args = parser.parse_args()
source = (args.source / 'src/venus/vkr_win32_shim.c').read_text(encoding='utf-8')

def function(name):
    start = source.index('\n' + name + '(') + 1
    brace = source.index('{', start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return 'static VKAPI_ATTR VkResult VKAPI_CALL ' + source[start:end] + '\n'

harness = r'''
#include <vulkan/vulkan.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
struct vkr_physical_device { bool host_external_memory_host; };
struct vkr_device { struct vkr_physical_device *physical_device; };
struct vkr_win32_device_entry {
 struct vkr_device *dev;
 struct { PFN_vkCreateBuffer CreateBuffer; PFN_vkCreateImage CreateImage; } saved_proc_table;
};
static struct vkr_physical_device physical;
static struct vkr_device device = { &physical };
static struct vkr_win32_device_entry entry;
static VkExternalMemoryHandleTypeFlags observed;
static VkImageTiling tiling;
static unsigned calls;
static struct vkr_win32_device_entry *vkr_win32_lookup_device(VkDevice d) { (void)d; return &entry; }
static VkExternalMemoryHandleTypeFlags vkr_win32_get_host_handle_type(struct vkr_device *d) {
 (void)d; return VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
}
/* Handle translation is tested separately; these inputs already use host types. */
static void vkr_win32_remap_external_handle_types_in_chain(const void *p) { (void)p; }
static VkResult VKAPI_CALL fake_buffer(VkDevice d, const VkBufferCreateInfo *info,
 const VkAllocationCallbacks *a, VkBuffer *b) {
 (void)d; (void)a; (void)b; observed=0; calls++;
 for (const VkBaseInStructure *n=info->pNext; n; n=n->pNext)
  if (n->sType==VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO)
   observed=((const VkExternalMemoryBufferCreateInfo *)n)->handleTypes;
 return VK_SUCCESS;
}
static VkResult VKAPI_CALL fake_image(VkDevice d, const VkImageCreateInfo *info,
 const VkAllocationCallbacks *a, VkImage *i) {
 (void)d; (void)a; (void)i; tiling=info->tiling; calls++; return VK_SUCCESS;
}
'''
harness += function('vkr_win32_CreateBuffer') + function('vkr_win32_CreateImage')
harness += r'''
int main(void) {
 entry.dev=&device;entry.saved_proc_table.CreateBuffer=fake_buffer;entry.saved_proc_table.CreateImage=fake_image;
 VkBufferCreateInfo buffer={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=65536,.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
 VkBuffer b; physical.host_external_memory_host=true;
 if(vkr_win32_CreateBuffer(VK_NULL_HANDLE,&buffer,NULL,&b)!=VK_SUCCESS || observed!=0) {
  fputs("host-pointer allocator's ordinary buffer was forced external\n",stderr);return 1;
 }
 physical.host_external_memory_host=false;
 if(vkr_win32_CreateBuffer(VK_NULL_HANDLE,&buffer,NULL,&b)!=VK_SUCCESS || observed!=VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT) {
  fputs("legacy external-memory buffer lost its native handle type\n",stderr);return 1;
 }
 VkExternalMemoryBufferCreateInfo external={.sType=VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO,.handleTypes=VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT};
 buffer.pNext=&external;physical.host_external_memory_host=true;
 if(vkr_win32_CreateBuffer(VK_NULL_HANDLE,&buffer,NULL,&b)!=VK_SUCCESS || observed!=external.handleTypes) {
  fputs("explicit host-pointer resource was changed\n",stderr);return 1;
 }
 VkExternalMemoryImageCreateInfo image_external={.sType=VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO,.handleTypes=VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT};
 VkImageCreateInfo image={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.pNext=&image_external,.tiling=VK_IMAGE_TILING_OPTIMAL};VkImage i;
 if(vkr_win32_CreateImage(VK_NULL_HANDLE,&image,NULL,&i)!=VK_SUCCESS || tiling!=VK_IMAGE_TILING_OPTIMAL) {
  fputs("host-pointer image was coerced to an unsupported linear layout\n",stderr);return 1;
 }
 image_external.handleTypes=VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
 if(vkr_win32_CreateImage(VK_NULL_HANDLE,&image,NULL,&i)!=VK_SUCCESS || tiling!=VK_IMAGE_TILING_LINEAR || calls!=5) {
  fputs("legacy exported-image linear layout was not retained\n",stderr);return 1;
 }
 puts("ok - host-pointer resources and legacy exported resources keep their own contracts");return 0;
}
'''
with tempfile.TemporaryDirectory() as temporary:
    path = Path(temporary)
    fixture = path / 'resource-shim.c'
    fixture.write_text(harness, encoding='utf-8')
    program = path / ('resource-shim.exe' if os.name == 'nt' else 'resource-shim')
    subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + ['-std=c11', str(fixture), '-o', str(program)], check=True)
    subprocess.run([str(program)], check=True, timeout=10)
