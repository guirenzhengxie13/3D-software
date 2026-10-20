// Local probe for the unmodified public Revopoint 3DViewer reference SDK.
// Deliberately does not connect a camera, start a stream, or initialize a driver
// with an authorization code. No initialization-check control is resolved/called.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

#include "hpp/APIExport.hpp"
#include "h/system.h"

namespace {
template <typename Function>
Function resolve(HMODULE module, const char* name) {
    const auto address = GetProcAddress(module, name);
    if (!address) {
        throw std::runtime_error(std::string("Missing expected SDK export: ") + name);
    }
    return reinterpret_cast<Function>(address);
}

struct ModuleCloser {
    void operator()(HINSTANCE__* value) const { if (value) FreeLibrary(value); }
};

std::string boundedString(const char* data, size_t capacity) {
    size_t length = 0;
    while (length < capacity && data[length] != '\0') ++length;
    return std::string(data, length);
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc != 2 || !std::filesystem::path(argv[1]).is_absolute()) {
        std::cerr << "Usage: public_sdk_probe.exe <absolute path to 3DCamera.dll>\n";
        return 2;
    }

    std::cout << "reference_only=true\nrange2_compatibility=unverified\n"
                 "streaming_authorization=unverified\ncapture_attempted=false\n";
    std::cout.flush();
    std::unique_ptr<HINSTANCE__, ModuleCloser> module(LoadLibraryExW(
        argv[1], nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS));
    if (!module) {
        std::cerr << "dll_loaded=false\nwindows_error=" << GetLastError() << '\n';
        return 3;
    }

    try {
        // These decorated names are the documented C++ APIs as exported by the
        // pinned Windows x64 DLL. Dynamic loading keeps DLL selection explicit.
        using SetBoolean = void (*)(bool);
        const auto setSdkNetwork = resolve<SetBoolean>(
            module.get(), "?setSdkEnableNetworking@cs@@YAX_N@Z");
        const auto setNetwork = resolve<SetBoolean>(
            module.get(), "?setEnableNetworking@cs@@YAX_N@Z");
        const auto enableLogging = resolve<SetBoolean>(
            module.get(), "?enableLoging@cs@@YAX_N@Z");
        using GetVersion = ERROR_CODE (*)(CS_SDK_VERSION**);
        const auto getVersion = resolve<GetVersion>(module.get(),
            "?getSdkVersion@cs@@YA?AW4ERROR_CODE@@PEAPEAUCS_SDK_VERSION_TAG@@@Z");
        const auto create = resolve<decltype(&createSystem)>(module.get(), "createSystem");
        const auto destroy = resolve<decltype(&deleteSystem)>(module.get(), "deleteSystem");
        const auto list = resolve<decltype(&systemCreateCameraInfoList)>(
            module.get(), "systemCreateCameraInfoList");
        const auto freeList = resolve<decltype(&systemDeleteCameraInfoList)>(
            module.get(), "systemDeleteCameraInfoList");

        // Disable the SDK's network discovery/transport and file logging before
        // creating its system context. No firewall/driver/system settings change.
        setSdkNetwork(false);
        setNetwork(false);
        enableLogging(false);
        std::cout << "dll_loaded=true\nnetworking_requested=false\n"
                     "sdk_file_logging_requested=false\n";

        CS_SDK_VERSION* version = nullptr;
        const auto versionStatus = getVersion(&version);
        std::cout << "version_status=" << static_cast<int>(versionStatus) << '\n';
        if (versionStatus != SUCCESS || !version || !version->version) {
            std::cerr << "SDK did not return version information.\n";
            return 4;
        }
        // Version information is SDK-owned; the public header provides no free.
        std::cout << "sdk_version=" << version->version << '\n';
        if (version->date) std::cout << "sdk_build_date=" << version->date << '\n';

        std::unique_ptr<CSystem, decltype(destroy)> system(create(), destroy);
        if (!system) {
            std::cerr << "system_context_created=false\n";
            return 5;
        }
        std::cout << "system_context_created=true\n";
        Sleep(1500);  // Allow ordinary USB arrival discovery to finish.
        int count = -1;
        std::unique_ptr<CameraInfo, decltype(freeList)> cameras(list(system.get(), &count), freeList);
        if (count < 0 || (count > 0 && !cameras)) {
            std::cerr << "enumeration_call_completed=false\n";
            return 6;
        }
        std::cout << "enumeration_call_completed=true\ncamera_count=" << count << '\n';
        for (int index = 0; index < count; ++index) {
            const CameraInfo& camera = cameras.get()[index];
            std::cout << "camera[" << index << "].name="
                      << boundedString(camera.name, sizeof(camera.name)) << '\n';
            std::cout << "camera[" << index << "].firmware="
                      << boundedString(camera.firmwareVersion, sizeof(camera.firmwareVersion)) << '\n';
            std::cout << "camera[" << index << "].serial=redacted\n";
        }
        if (count == 0) {
            std::cout << "note=No camera reported; no device/authorization/stream verification performed.\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "probe_error=" << error.what() << '\n';
        return 7;
    }
}
