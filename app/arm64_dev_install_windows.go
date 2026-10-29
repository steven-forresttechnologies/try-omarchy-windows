//go:build windows && arm64dev

package main

import (
	"archive/zip"
	"crypto/sha256"
	"debug/pe"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

const armDevelopmentMarker = "arm64-development.json"

var armDevelopmentGuestFiles = []string{"build-spec.json", "guest-manifest.json", "vmlinuz-linux", "initramfs-linux.img", "rootfs.ext4"}

type armDevelopmentPins struct {
	GuestManifest  string `json:"guestManifestSHA256"`
	RuntimeArchive string `json:"runtimeArchiveSHA256"`
}

type armDevelopmentIdentity struct {
	Version      int                `json:"version"`
	Architecture string             `json:"architecture"`
	Pins         armDevelopmentPins `json:"pins"`
}

// Development inputs are local hash pins supplied by the developer. They are
// deliberately independent of the public release/update trust envelope.
func validateARMDevelopmentPins(pins armDevelopmentPins) error {
	if !validSHA256(pins.GuestManifest) || !validSHA256(pins.RuntimeArchive) {
		return fmt.Errorf("ARM development requires explicit guest-manifest and runtime-archive SHA256 pins")
	}
	return nil
}

// Reject all reparse points in the installation ancestry, including junctions.
// This entry never adopts an existing unmarked directory or a moved install.
func armDevelopmentPath(path string) (string, error) {
	if !filepath.IsAbs(path) {
		return "", fmt.Errorf("ARM development paths must be absolute")
	}
	path = filepath.Clean(path)
	for current := path; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err == nil {
			if info.Mode()&os.ModeSymlink != 0 {
				return "", fmt.Errorf("ARM development path contains a link: %s", current)
			}
			wide, err := syscall.UTF16PtrFromString(current)
			if err != nil {
				return "", err
			}
			attributes, err := syscall.GetFileAttributes(wide)
			if err != nil {
				return "", err
			}
			if attributes&fileAttributeReparsePoint != 0 {
				return "", fmt.Errorf("ARM development path contains a reparse point: %s", current)
			}
		} else if !os.IsNotExist(err) {
			return "", err
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
	}
	return path, nil
}

func armDevelopmentHash(path string) (string, error) {
	if _, err := armDevelopmentPath(path); err != nil {
		return "", err
	}
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return "", fmt.Errorf("not a regular candidate file: %s", path)
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func verifyARMDevelopmentFile(path, digest string) error {
	if !validSHA256(digest) {
		return fmt.Errorf("missing hash for %s", path)
	}
	got, err := armDevelopmentHash(path)
	if err != nil {
		return err
	}
	if got != digest {
		return fmt.Errorf("candidate checksum mismatch: %s", path)
	}
	return nil
}

func copyARMDevelopmentFile(source, destination, digest string) error {
	if _, err := armDevelopmentPath(source); err != nil {
		return err
	}
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("candidate source is not a regular file")
	}
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	if err != nil {
		return err
	}
	if err = setSparse(out); err == nil {
		err = sparseCopy(out, in, info.Size(), getUI())
	}
	if err == nil {
		err = out.Sync()
	}
	closeErr := out.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return verifyARMDevelopmentFile(destination, digest)
}

func armDevelopmentGuestArchitecture(dir string) error {
	for _, name := range []string{"build-spec.json", "guest-manifest.json"} {
		data, err := readBoundedRegularFile(filepath.Join(dir, name), 1<<20)
		if err != nil {
			return err
		}
		var metadata struct {
			Image struct {
				Architecture string `json:"architecture"`
			} `json:"image"`
			Guest struct {
				Architecture string `json:"architecture"`
			} `json:"guest"`
		}
		if err := json.Unmarshal(data, &metadata); err != nil {
			return err
		}
		architecture := metadata.Guest.Architecture
		if name == "build-spec.json" {
			architecture = metadata.Image.Architecture
		}
		if architecture != "aarch64" {
			return fmt.Errorf("%s is not an aarch64 guest", name)
		}
	}
	return nil
}

func safeARMDevelopmentArchiveName(name string) bool {
	if name == "" || strings.ContainsAny(name, "\\:\x00") || strings.HasPrefix(name, "/") ||
		!filepath.IsLocal(filepath.FromSlash(strings.TrimSuffix(name, "/"))) {
		return false
	}
	for _, part := range strings.Split(strings.TrimSuffix(name, "/"), "/") {
		if part == "" || part == "." || part == ".." || strings.TrimRight(part, " .") != part {
			return false
		}
		base := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		if base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" ||
			(len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '0' && base[3] <= '9') {
			return false
		}
	}
	return true
}

func validateARMDevelopmentArchive(path string) error {
	r, err := zip.OpenReader(path)
	if err != nil {
		return err
	}
	defer r.Close()
	seen := map[string]bool{}
	var total uint64
	for _, entry := range r.File {
		key := strings.ToLower(strings.TrimSuffix(entry.Name, "/"))
		if !safeARMDevelopmentArchiveName(entry.Name) || seen[key] || entry.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("unsafe or duplicate ARM runtime archive entry: %s", entry.Name)
		}
		seen[key] = true
		if entry.UncompressedSize64 > 2<<30 || total > (2<<30)-entry.UncompressedSize64 {
			return fmt.Errorf("ARM runtime archive is too large")
		}
		total += entry.UncompressedSize64
	}
	return nil
}

func verifyARMDevelopmentRuntimePin(root, digest string) error {
	archive := filepath.Join(root, "runtime.zip")
	if err := verifyARMDevelopmentFile(archive, digest); err != nil {
		return err
	}
	r, err := zip.OpenReader(archive)
	if err != nil {
		return err
	}
	defer r.Close()
	for _, entry := range r.File {
		if entry.Name != "provenance/runtime-manifest.json" {
			continue
		}
		if entry.UncompressedSize64 > 4<<20 {
			return fmt.Errorf("runtime manifest is too large")
		}
		in, err := entry.Open()
		if err != nil {
			return err
		}
		h := sha256.New()
		_, copyErr := io.Copy(h, io.LimitReader(in, 4<<20+1))
		closeErr := in.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
		return verifyARMDevelopmentFile(filepath.Join(root, "runtime", "provenance", "runtime-manifest.json"), hex.EncodeToString(h.Sum(nil)))
	}
	return fmt.Errorf("pinned runtime archive has no manifest")
}

func verifyARMDevelopmentRuntime(root string) error {
	data, err := readBoundedRegularFile(filepath.Join(root, "provenance", "runtime-manifest.json"), 4<<20)
	if err != nil {
		return err
	}
	var manifest struct {
		Files []struct {
			Path   string `json:"path"`
			Size   int64  `json:"size"`
			SHA256 string `json:"sha256"`
		} `json:"files"`
	}
	if err := json.Unmarshal(data, &manifest); err != nil {
		return err
	}
	if len(manifest.Files) == 0 {
		return fmt.Errorf("runtime manifest has no files")
	}
	expected := map[string]bool{"provenance/runtime-manifest.json": true}
	for _, file := range manifest.Files {
		key := strings.ToLower(file.Path)
		if !safeARMDevelopmentArchiveName(file.Path) || expected[key] {
			return fmt.Errorf("invalid runtime manifest path")
		}
		expected[key] = true
		path := filepath.Join(root, filepath.FromSlash(file.Path))
		if err := verifyARMDevelopmentFile(path, file.SHA256); err != nil {
			return err
		}
		info, err := os.Stat(path)
		if err != nil || info.Size() != file.Size {
			return fmt.Errorf("runtime file size mismatch: %s", file.Path)
		}
		if strings.HasPrefix(key, "bin/") && (strings.HasSuffix(key, ".exe") || strings.HasSuffix(key, ".dll") || strings.HasSuffix(key, ".drv")) {
			binary, err := pe.Open(path)
			if err != nil {
				return err
			}
			machine := binary.Machine
			binary.Close()
			if machine != pe.IMAGE_FILE_MACHINE_ARM64 {
				return fmt.Errorf("runtime contains a non-ARM64 binary: %s", file.Path)
			}
		}
	}
	for _, required := range []string{"bin/qemu-system-aarch64w.exe", "bin/qemu-img.exe", "bin/libvirglrenderer-1.dll", "bin/vulkan-1.dll"} {
		if !expected[required] {
			return fmt.Errorf("ARM runtime is missing %s", required)
		}
	}
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if _, err := armDevelopmentPath(path); err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if !expected[strings.ToLower(filepath.ToSlash(relative))] {
			return fmt.Errorf("unverified runtime file: %s", relative)
		}
		return nil
	})
}

// Called after the complete pinned runtime inventory has been verified. CPU
// candidates remain usable, but GPU opt-in requires the tested private stack.
func verifyARMDevelopmentGraphics(root string) error {
	for _, name := range []string{"bin/vulkan_dzn.dll", "bin/libspirv_to_dxil.dll", "bin/dxil.dll",
		"LICENSES/DirectXShaderCompiler/LICENCE-MIT.txt", "LICENSES/DirectXShaderCompiler/LICENSE-LLVM.txt", "LICENSES/DirectXShaderCompiler/LICENSE-MS.txt"} {
		path := filepath.Join(root, filepath.FromSlash(name))
		if _, err := armDevelopmentPath(path); err != nil {
			return err
		}
		if info, err := os.Stat(path); err != nil || !info.Mode().IsRegular() {
			return fmt.Errorf("ARM graphics require the source-built private Dozen runtime")
		}
	}
	data, err := readBoundedRegularFile(filepath.Join(root, "provenance", "dxc-arm64.lock.json"), 65536)
	if err != nil {
		return err
	}
	var dxc struct {
		Schema  int               `json:"schema"`
		Version string            `json:"version"`
		Files   map[string]string `json:"files"`
	}
	if json.Unmarshal(data, &dxc) != nil || dxc.Schema != 1 || dxc.Version != "1.9.2609" {
		return fmt.Errorf("ARM graphics require the reviewed private DXIL validator")
	}
	if err := verifyARMDevelopmentFile(filepath.Join(root, "bin", "dxil.dll"), dxc.Files["bin/arm64/dxil.dll"]); err != nil {
		return err
	}
	data, err = readBoundedRegularFile(filepath.Join(root, "provenance", "mesa-arm64.lock.json"), 65536)
	if err != nil {
		return err
	}
	var mesa struct {
		Schema  int    `json:"schema"`
		Version string `json:"version"`
		SHA256  string `json:"sha256"`
		Patches []struct {
			File string `json:"file"`
		} `json:"patches"`
	}
	if json.Unmarshal(data, &mesa) != nil || mesa.Schema != 1 || mesa.Version != "26.2.5" || !validSHA256(mesa.SHA256) {
		return fmt.Errorf("ARM graphics require the reviewed Mesa source profile")
	}
	mesaPatched := false
	for _, patch := range mesa.Patches {
		mesaPatched = mesaPatched || patch.File == "patches/mesa/0001-fix-host-import-resource-requirements-and-binding.patch"
	}
	if !mesaPatched {
		return fmt.Errorf("ARM graphics require the Mesa host-import corrections")
	}
	data, err = readBoundedRegularFile(filepath.Join(root, "provenance", "sources.lock.json"), 65536)
	if err != nil {
		return err
	}
	var sources struct {
		Virglrenderer struct {
			Patches []struct {
				File string `json:"file"`
			} `json:"patches"`
		} `json:"virglrenderer"`
	}
	if err := json.Unmarshal(data, &sources); err != nil {
		return err
	}
	required := map[string]bool{
		"patches/virglrenderer/0007-complete-windows-resource-error-replies.patch": false,
		"patches/virglrenderer/0008-preserve-host-pointer-resource-classes.patch":  false,
	}
	for _, patch := range sources.Virglrenderer.Patches {
		if _, ok := required[patch.File]; ok {
			required[patch.File] = true
		}
	}
	for name, found := range required {
		if !found {
			return fmt.Errorf("ARM graphics runtime is missing %s", name)
		}
	}
	data, err = readBoundedRegularFile(filepath.Join(root, "bin", "dzn-arm64.json"), 65536)
	if err != nil {
		return err
	}
	var icd struct {
		ICD struct {
			Library string `json:"library_path"`
		} `json:"ICD"`
	}
	if json.Unmarshal(data, &icd) != nil || icd.ICD.Library != "./vulkan_dzn.dll" {
		return fmt.Errorf("ARM graphics ICD must select its private relative driver")
	}
	return nil
}

// A private sibling staging directory is published only after all copied
// artifacts and the new overlay have been verified. An interrupted install
// never makes an unmarked existing disk eligible for reuse.
func prepareARMDevelopment(root, guest, archive string, pins armDevelopmentPins) error {
	if err := validateARMDevelopmentPins(pins); err != nil {
		return err
	}
	var err error
	root, err = armDevelopmentPath(root)
	if err != nil {
		return err
	}
	// A new leaf cannot be resolved by EvalSymlinks, but its existing parent
	// can. Expand Windows 8.3 aliases before checking installation overlap.
	canonical, err := filepath.EvalSymlinks(root)
	if os.IsNotExist(err) {
		parent, parentErr := filepath.EvalSymlinks(filepath.Dir(root))
		if parentErr != nil {
			return parentErr
		}
		canonical, err = filepath.Join(parent, filepath.Base(root)), nil
	}
	if err != nil {
		return err
	}
	root = canonical
	defaultRoot := filepath.Join(os.Getenv("LOCALAPPDATA"), defaultDataDirectoryName)
	if pathsOverlapWindows(root, defaultRoot) {
		return fmt.Errorf("ARM development requires a separate installation directory")
	}
	if _, err := os.Lstat(root); err == nil {
		return verifyARMDevelopmentInstall(root, pins)
	} else if !os.IsNotExist(err) {
		return err
	}
	data, err := readBoundedRegularFile(filepath.Join(guest, "SHA256SUMS"), maxSumsBytes)
	if err != nil {
		return err
	}
	sums, err := parseVerifiedSums(data, pins.GuestManifest)
	if err != nil {
		return err
	}
	stage, err := os.MkdirTemp(filepath.Dir(root), ".try-omarchy-arm64-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	for _, name := range []string{"guest", "runtime", "vm"} {
		if err := os.Mkdir(filepath.Join(stage, name), 0700); err != nil {
			return err
		}
	}
	identity := armDevelopmentIdentity{Version: 1, Architecture: "aarch64", Pins: pins}
	if err := os.WriteFile(filepath.Join(stage, "guest", "SHA256SUMS"), data, 0600); err != nil {
		return err
	}
	for _, name := range armDevelopmentGuestFiles {
		if err := copyARMDevelopmentFile(filepath.Join(guest, name), filepath.Join(stage, "guest", name), sums[name]); err != nil {
			return err
		}
	}
	if err := armDevelopmentGuestArchitecture(filepath.Join(stage, "guest")); err != nil {
		return err
	}
	if err := copyARMDevelopmentFile(archive, filepath.Join(stage, "runtime.zip"), pins.RuntimeArchive); err != nil {
		return err
	}
	if err := validateARMDevelopmentArchive(filepath.Join(stage, "runtime.zip")); err != nil {
		return err
	}
	if err := unzipTree(filepath.Join(stage, "runtime.zip"), filepath.Join(stage, "runtime"), getUI()); err != nil {
		return err
	}
	if err := verifyARMDevelopmentRuntime(filepath.Join(stage, "runtime")); err != nil {
		return err
	}
	if err := verifyARMDevelopmentRuntimePin(stage, pins.RuntimeArchive); err != nil {
		return err
	}
	if err := createQcow2Overlay(filepath.Join(stage, "vm", "disk.qcow2"), "../guest/rootfs.ext4", 24<<30); err != nil {
		return err
	}
	marker, err := json.MarshalIndent(identity, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(stage, armDevelopmentMarker), marker, 0600); err != nil {
		return err
	}
	// Rename refuses an existing nonempty directory; do not replace any install.
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		return fmt.Errorf("ARM development destination appeared during installation")
	}
	return os.Rename(stage, root)
}

func verifyARMDevelopmentInstall(root string, pins armDevelopmentPins) error {
	data, err := readBoundedRegularFile(filepath.Join(root, armDevelopmentMarker), 1<<20)
	if err != nil {
		return fmt.Errorf("refusing unmarked ARM development directory: %w", err)
	}
	var identity armDevelopmentIdentity
	if json.Unmarshal(data, &identity) != nil || identity.Version != 1 || identity.Architecture != "aarch64" || identity.Pins != pins {
		return fmt.Errorf("ARM development identity does not match the requested artifacts")
	}
	sumsData, err := readBoundedRegularFile(filepath.Join(root, "guest", "SHA256SUMS"), maxSumsBytes)
	if err != nil {
		return err
	}
	sums, err := parseVerifiedSums(sumsData, pins.GuestManifest)
	if err != nil {
		return err
	}
	for _, name := range armDevelopmentGuestFiles {
		if err := verifyARMDevelopmentFile(filepath.Join(root, "guest", name), sums[name]); err != nil {
			return err
		}
	}
	if err := armDevelopmentGuestArchitecture(filepath.Join(root, "guest")); err != nil {
		return err
	}
	if err := verifyARMDevelopmentRuntimePin(root, pins.RuntimeArchive); err != nil {
		return err
	}
	if err := verifyARMDevelopmentRuntime(filepath.Join(root, "runtime")); err != nil {
		return err
	}
	disk := filepath.Join(root, "vm", "disk.qcow2")
	if _, err := armDevelopmentPath(disk); err != nil {
		return err
	}
	ok, err := qcow2OverlayMatches(disk, "../guest/rootfs.ext4", 24<<30)
	if err != nil {
		return err
	}
	if !ok {
		return fmt.Errorf("ARM development disk has an unexpected backing or capacity")
	}
	return nil
}
