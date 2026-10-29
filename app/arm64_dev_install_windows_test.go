//go:build windows && arm64dev

package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unsafe"
)

func armTestHash(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func armTestCandidate(t *testing.T, arch string) (string, string, armDevelopmentPins) {
	t.Helper()
	base := t.TempDir()
	guest := filepath.Join(base, "guest")
	if err := os.Mkdir(guest, 0700); err != nil {
		t.Fatal(err)
	}
	var sums strings.Builder
	for _, name := range armDevelopmentGuestFiles {
		data := []byte("candidate " + name)
		if strings.HasSuffix(name, ".json") {
			section := "guest"
			if name == "build-spec.json" {
				section = "image"
			}
			data = []byte(fmt.Sprintf(`{%q:{"architecture":%q}}`, section, arch))
		}
		if err := os.WriteFile(filepath.Join(guest, name), data, 0600); err != nil {
			t.Fatal(err)
		}
		fmt.Fprintf(&sums, "%s  %s\n", armTestHash(data), name)
	}
	if err := os.WriteFile(filepath.Join(guest, "SHA256SUMS"), []byte(sums.String()), 0600); err != nil {
		t.Fatal(err)
	}
	// A minimal COFF header lets debug/pe check the machine independently of
	// the host architecture without executing a fixture binary.
	image := make([]byte, 128)
	copy(image, "MZ")
	binary.LittleEndian.PutUint32(image[60:], 64)
	copy(image[64:], "PE\x00\x00")
	binary.LittleEndian.PutUint16(image[68:], 0xaa64)
	binary.LittleEndian.PutUint32(image[76:], 88)
	binary.LittleEndian.PutUint32(image[88:], 4)
	files := map[string][]byte{}
	for _, name := range []string{"qemu-system-aarch64w.exe", "qemu-img.exe", "libvirglrenderer-1.dll", "vulkan-1.dll"} {
		files["bin/"+name] = image
	}
	type entry struct {
		Path   string `json:"path"`
		Size   int    `json:"size"`
		SHA256 string `json:"sha256"`
	}
	var manifest struct {
		Files []entry `json:"files"`
	}
	for path, data := range files {
		manifest.Files = append(manifest.Files, entry{path, len(data), armTestHash(data)})
	}
	encoded, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	files["provenance/runtime-manifest.json"] = encoded
	archive := filepath.Join(base, "runtime.zip")
	out, err := os.Create(archive)
	if err != nil {
		t.Fatal(err)
	}
	z := zip.NewWriter(out)
	for name, data := range files {
		w, err := z.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = w.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	if err := out.Close(); err != nil {
		t.Fatal(err)
	}
	archiveBytes, err := os.ReadFile(archive)
	if err != nil {
		t.Fatal(err)
	}
	return guest, archive, armDevelopmentPins{armTestHash([]byte(sums.String())), armTestHash(archiveBytes)}
}

func TestARMDevelopmentInstallAndDiskOwnership(t *testing.T) {
	guest, archive, pins := armTestCandidate(t, "aarch64")
	root := filepath.Join(t.TempDir(), "installation")
	if err := prepareARMDevelopment(root, guest, archive, pins); err != nil {
		t.Fatal(err)
	}
	disk := filepath.Join(root, "vm", "disk.qcow2")
	before, err := os.ReadFile(disk)
	if err != nil {
		t.Fatal(err)
	}
	if err := prepareARMDevelopment(root, guest, archive, pins); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(disk)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Fatal("second launch changed the guest disk")
	}
	wrong := pins
	wrong.RuntimeArchive = strings.Repeat("a", 64)
	if err := prepareARMDevelopment(root, guest, archive, wrong); err == nil {
		t.Fatal("accepted mismatched runtime identity")
	}
	if err := os.Remove(filepath.Join(root, armDevelopmentMarker)); err != nil {
		t.Fatal(err)
	}
	if err := prepareARMDevelopment(root, guest, archive, pins); err == nil {
		t.Fatal("adopted an unmarked guest disk")
	}
	after, _ = os.ReadFile(disk)
	if string(before) != string(after) {
		t.Fatal("refusal modified an unmarked disk")
	}
}

func TestARMDevelopmentRejectsWrongArtifactsBeforePublication(t *testing.T) {
	for _, arch := range []string{"x86_64", "aarch64"} {
		t.Run(arch, func(t *testing.T) {
			guest, archive, pins := armTestCandidate(t, arch)
			if arch == "aarch64" {
				if err := os.WriteFile(filepath.Join(guest, "vmlinuz-linux"), []byte("tampered"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			root := filepath.Join(t.TempDir(), "installation")
			if err := prepareARMDevelopment(root, guest, archive, pins); err == nil {
				t.Fatal("accepted wrong guest")
			}
			if _, err := os.Lstat(root); !os.IsNotExist(err) {
				t.Fatal("published an invalid candidate")
			}
		})
	}
}

func TestARMDevelopmentRechecksPinnedMetadata(t *testing.T) {
	guest, archive, pins := armTestCandidate(t, "aarch64")
	root := filepath.Join(t.TempDir(), "installation")
	if err := prepareARMDevelopment(root, guest, archive, pins); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "runtime", "bin", "vulkan-1.dll")
	if err := os.WriteFile(path, []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := prepareARMDevelopment(root, guest, archive, pins); err == nil {
		t.Fatal("accepted a changed runtime")
	}
	manifest := filepath.Join(root, "runtime", "provenance", "runtime-manifest.json")
	if err := os.WriteFile(manifest, []byte(`{"files":[]}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := verifyARMDevelopmentRuntimePin(root, pins.RuntimeArchive); err == nil {
		t.Fatal("accepted replaced runtime manifest")
	}
}

func TestARMDevelopmentArchiveNames(t *testing.T) {
	for _, name := range []string{"../escape", "/absolute", "C:/drive", "bin\\x.dll", "bin/x.dll:stream", "bin/CON.dll", "bin/x. ", "bin//x.dll"} {
		if safeARMDevelopmentArchiveName(name) {
			t.Errorf("accepted %q", name)
		}
	}
	if !safeARMDevelopmentArchiveName("bin/vulkan-1.dll") {
		t.Fatal("rejected a normal runtime path")
	}
}

func TestARMDevelopmentRuntimeRejectsMixedMachines(t *testing.T) {
	guest, archive, pins := armTestCandidate(t, "aarch64")
	root := filepath.Join(t.TempDir(), "installation")
	if err := prepareARMDevelopment(root, guest, archive, pins); err != nil {
		t.Fatal(err)
	}
	runtimeRoot := filepath.Join(root, "runtime")
	path := filepath.Join(runtimeRoot, "bin", "vulkan-1.dll")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	binary.LittleEndian.PutUint16(data[68:], 0x8664)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	manifestPath := filepath.Join(runtimeRoot, "provenance", "runtime-manifest.json")
	manifest, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(manifest, &document); err != nil {
		t.Fatal(err)
	}
	for _, item := range document["files"].([]any) {
		file := item.(map[string]any)
		if file["path"] == "bin/vulkan-1.dll" {
			file["sha256"] = armTestHash(data)
		}
	}
	manifest, _ = json.Marshal(document)
	if err := os.WriteFile(manifestPath, manifest, 0600); err != nil {
		t.Fatal(err)
	}
	if err := verifyARMDevelopmentRuntime(runtimeRoot); err == nil || !strings.Contains(err.Error(), "non-ARM64") {
		t.Fatalf("mixed-architecture runtime: %v", err)
	}
}

func TestARMDevelopmentRejectsDirectoryLinks(t *testing.T) {
	base := t.TempDir()
	link := filepath.Join(base, "link")
	if err := os.Symlink(t.TempDir(), link); err != nil {
		t.Skipf("directory symlinks unavailable: %v", err)
	}
	if _, err := armDevelopmentPath(filepath.Join(link, "new-install")); err == nil {
		t.Fatal("accepted an installation below a directory link")
	}
}

func TestARMDevelopmentRejectsNormalInstallThroughShortParent(t *testing.T) {
	base := t.TempDir()
	t.Setenv("LOCALAPPDATA", base)
	normal := filepath.Join(base, defaultDataDirectoryName)
	if err := os.Mkdir(normal, 0700); err != nil {
		t.Fatal(err)
	}
	wide, err := syscall.UTF16PtrFromString(normal)
	if err != nil {
		t.Fatal(err)
	}
	var buffer [32768]uint16
	length, _, _ := kernel32.NewProc("GetShortPathNameW").Call(uintptr(unsafe.Pointer(wide)), uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)))
	if length == 0 || length >= uintptr(len(buffer)) {
		t.Skip("short paths are unavailable on this volume")
	}
	short := syscall.UTF16ToString(buffer[:length])
	if strings.EqualFold(filepath.Clean(short), filepath.Clean(normal)) {
		t.Skip("the volume did not create an 8.3 alias")
	}
	guest, archive, pins := armTestCandidate(t, "aarch64")
	root := filepath.Join(short, "new-arm-development")
	if err := prepareARMDevelopment(root, guest, archive, pins); err == nil || !strings.Contains(err.Error(), "separate installation") {
		t.Fatalf("normal installation short-path parent: %v", err)
	}
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		t.Fatal("published below the normal installation through its short alias")
	}
}

func TestARMDevelopmentQEMUIsolatesDynamicLibraries(t *testing.T) {
	cmd := exec.Command(filepath.Join(t.TempDir(), "bin", "qemu-system-aarch64w.exe"))
	cmd.Env = []string{"PATH=C:\\OtherApp", "sdl_render_driver=opengles2", "SDL_OPENGL_LIBRARY=other.dll", "KEEP=value"}
	configureARM64DevelopmentQEMU(cmd, false)
	if cmd.Dir != filepath.Dir(cmd.Path) {
		t.Fatal("QEMU working directory is outside its verified runtime")
	}
	joined := strings.Join(cmd.Env, "\n")
	if strings.Contains(joined, "OtherApp") || strings.Contains(joined, "other.dll") || strings.Contains(joined, "opengles2") {
		t.Fatalf("inherited foreign graphics loader settings: %v", cmd.Env)
	}
	if !strings.Contains(joined, "SDL_RENDER_DRIVER=software") || !strings.Contains(joined, "KEEP=value") {
		t.Fatalf("missing isolated CPU display settings: %v", cmd.Env)
	}
}

func TestARMDevelopmentGPUUsesOnlyPrivateICD(t *testing.T) {
	cmd := exec.Command(filepath.Join(t.TempDir(), "bin", "qemu-system-aarch64w.exe"))
	cmd.Env = []string{"VK_DRIVER_FILES=foreign.json", "VK_ICD_FILENAMES=other.json", "WINQ_DMABUF_SHIM_OFF=0", "SDL_RENDER_DRIVER=opengles2", "VK_LOADER_LAYERS_ENABLE=foreign-layer", "VK_LOADER_LAYERS_ALLOW=foreign-layer"}
	configureARM64DevelopmentQEMU(cmd, true)
	joined := strings.Join(cmd.Env, "\n")
	if strings.Contains(joined, "foreign.json") || strings.Contains(joined, "other.json") || strings.Contains(joined, "SDL_RENDER_DRIVER=") || strings.Contains(joined, "foreign-layer") {
		t.Fatalf("inherited GPU configuration: %v", cmd.Env)
	}
	if !strings.Contains(joined, "VK_DRIVER_FILES="+filepath.Join(cmd.Dir, "dzn-arm64.json")) || !strings.Contains(joined, "WINQ_DMABUF_SHIM_OFF=1") || !strings.Contains(joined, "VK_LOADER_LAYERS_DISABLE=~implicit~") {
		t.Fatalf("missing private ICD or tested presentation route: %v", cmd.Env)
	}
	guest, archive, pins := armTestCandidate(t, "aarch64")
	root := filepath.Join(t.TempDir(), "installation")
	if err := prepareARMDevelopment(root, guest, archive, pins); err != nil {
		t.Fatal(err)
	}
	if err := verifyARMDevelopmentGraphics(filepath.Join(root, "runtime")); err == nil {
		t.Fatal("CPU-only candidate was accepted for GPU use")
	}
}

func TestARMDevelopmentGraphicsProfileBindsValidatorAndICD(t *testing.T) {
	root := t.TempDir()
	write := func(name, value string) {
		t.Helper()
		path := filepath.Join(root, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	// This profile check follows the complete pinned ZIP/inventory/PE check.
	// Here the stand-ins isolate the additional graphics contracts.
	for _, name := range []string{"bin/vulkan_dzn.dll", "bin/libspirv_to_dxil.dll", "bin/dxil.dll",
		"LICENSES/DirectXShaderCompiler/LICENCE-MIT.txt", "LICENSES/DirectXShaderCompiler/LICENSE-LLVM.txt", "LICENSES/DirectXShaderCompiler/LICENSE-MS.txt"} {
		write(name, "fixture")
	}
	write("provenance/dxc-arm64.lock.json", `{"schema":1,"version":"1.9.2609","files":{"bin/arm64/dxil.dll":"`+armTestHash([]byte("fixture"))+`"}}`)
	write("provenance/mesa-arm64.lock.json", `{"schema":1,"version":"26.2.5","sha256":"`+strings.Repeat("a", 64)+`","patches":[{"file":"patches/mesa/0001-fix-host-import-resource-requirements-and-binding.patch"}]}`)
	write("provenance/sources.lock.json", `{"virglrenderer":{"patches":[{"file":"patches/virglrenderer/0007-complete-windows-resource-error-replies.patch"},{"file":"patches/virglrenderer/0008-preserve-host-pointer-resource-classes.patch"}]}}`)
	write("bin/dzn-arm64.json", `{"ICD":{"library_path":"./vulkan_dzn.dll"}}`)
	if err := verifyARMDevelopmentGraphics(root); err != nil {
		t.Fatal(err)
	}
	write("bin/dxil.dll", "changed validator")
	if err := verifyARMDevelopmentGraphics(root); err == nil {
		t.Fatal("accepted a validator outside the reviewed DXC profile")
	}
	write("bin/dxil.dll", "fixture")
	write("bin/dzn-arm64.json", `{"ICD":{"library_path":"C:/AnotherApplication/vulkan_dzn.dll"}}`)
	if err := verifyARMDevelopmentGraphics(root); err == nil {
		t.Fatal("accepted a driver outside the private runtime")
	}
}
