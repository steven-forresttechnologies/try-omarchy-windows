#!/usr/bin/env python3
"""Compile the Windows resource reply and client decoder against a byte stream."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def function(source, signature):
    start = source.index(signature)
    end = source.index("\n}\n", start) + 3
    return source[start:end]


parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
args = parser.parse_args()
server = (args.source / "src/proxy/proxy_server.c").read_text(encoding="utf-8")
client = (args.source / "src/proxy/proxy_socket.c").read_text(encoding="utf-8")
start = server.index("case RENDER_CONTEXT_OP_CREATE_RESOURCE: {")
end = server.index("case RENDER_CONTEXT_OP_IMPORT_RESOURCE:", start)
dispatch = server[start:end]
fixture = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef int SOCKET;
#define RENDER_CONTEXT_OP_CREATE_RESOURCE 1
#define VIRGL_RESOURCE_FD_INVALID 0
#define VIRGL_RESOURCE_FD_SHM 1
#define proxy_log(...) ((void)0)
struct proxy_socket { int fd; };
struct render_context_op_create_resource_reply {
    int fd_type;
    uint32_t map_info;
    uint64_t vulkan_info;
};
struct server_context_worker { int socket_fd; uint32_t ctx_id; };
struct server_thread_state { int renderer_mutex; };
static unsigned char request[128], response[512];
static size_t request_size, request_pos, response_size, response_pos;
static bool export_ok;
static void mtx_lock(int *mutex) { (void)mutex; }
static void mtx_unlock(int *mutex) { (void)mutex; }
static bool server_recv_all(int fd, void *data, size_t size) {
    (void)fd;
    if (size > request_size - request_pos) return false;
    memcpy(data, request + request_pos, size); request_pos += size; return true;
}
static bool server_send_all(int fd, const void *data, size_t size) {
    (void)fd; assert(response_size + size <= sizeof(response));
    memcpy(response + response_size, data, size); response_size += size; return true;
}
static bool recv_all(SOCKET fd, void *data, size_t size) {
    (void)fd;
    /* A real stream waits here when the descriptor count was omitted. */
    if (size > response_size - response_pos) return false;
    memcpy(data, response + response_pos, size); response_pos += size; return true;
}
static bool vkr_renderer_create_resource(uint32_t ctx, uint32_t resource,
    uint64_t blob, uint64_t size, uint32_t flags,
    int *type, int *fd, uint32_t *map, uint64_t *info) {
    assert(ctx == 7 && resource == 11 && blob == 13 && size == 4096 && flags == 3);
    if (!export_ok) return false;
    *type = VIRGL_RESOURCE_FD_SHM; *fd = 29; *map = 2; *info = 0;
    return true;
}
'''
if "static bool\nserver_send_reply(" in server:
    fixture += function(server, "static bool\nserver_send_reply(")
fixture += function(server, "static bool\nserver_send_reply_with_fds(")
fixture += function(client, "bool\nproxy_socket_receive_reply_with_fds(")
fixture += r'''
static void dispatch_resource(void) {
    struct server_context_worker worker = { .socket_fd = 5, .ctx_id = 7 };
    struct server_context_worker *w = &worker;
    struct server_thread_state server = {0};
    struct server_thread_state *state = &server;
    switch (RENDER_CONTEXT_OP_CREATE_RESOURCE) {
''' + dispatch + r'''
    }
    return;
done:
    assert(!"incomplete request");
}
static void append_request(const void *data, size_t size) {
    memcpy(request + request_size, data, size); request_size += size;
}
static void send_resource(bool success) {
    uint32_t id = 11, flags = 3; uint64_t blob = 13, size = 4096;
    request_size = request_pos = 0;
    append_request(&id, sizeof(id)); append_request(&blob, sizeof(blob));
    append_request(&size, sizeof(size)); append_request(&flags, sizeof(flags));
    export_ok = success; dispatch_resource(); assert(request_pos == request_size);
}
int main(void) {
    struct proxy_socket socket = { .fd = 9 };
    /* Rejection followed by success must not stall or desynchronize the stream. */
    for (int i = 0; i < 4; i++) {
        bool success = i % 2;
        send_resource(success);
        struct render_context_op_create_resource_reply reply = {0};
        int fd = -1, count = -1;
        if (!proxy_socket_receive_reply_with_fds(&socket, &reply, sizeof(reply), &fd, 1, &count)) {
            fputs("resource reply omitted its descriptor count\n", stderr);
            return 1;
        }
        assert(reply.fd_type == (success ? VIRGL_RESOURCE_FD_SHM : VIRGL_RESOURCE_FD_INVALID));
        assert(count == (success ? 1 : 0));
        assert(fd == (success ? 29 : -1));
        assert(response_pos == response_size);
    }
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="proxy-resource-reply-") as temp:
    c = Path(temp) / "reply.c"
    exe = Path(temp) / "reply.exe"
    c.write_text(fixture, encoding="utf-8")
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra",
                    "-Werror", "-Wno-unused-function", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)
print("ok - rejected Windows resource replies include an empty descriptor list")
