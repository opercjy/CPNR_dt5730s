#include "DigitizerRecovery.h"
#include "CaenDigitizer.h"
#include "DT5730Status.h"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <memory>
#include <ostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unistd.h>

void RefuseRecoveryWithLegacyFrontend() {
  // Also protect already-running frontends built before ownership locking.
  // New frontends/recovery serialize at the CAEN handle itself.
  for (const auto& entry : std::filesystem::directory_iterator("/proc")) {
    const std::string pid = entry.path().filename().string();
    // /proc/self and /proc/thread-self alias this process too. Only numeric
    // process directories can represent another PID.
    if (pid.empty() || pid.find_first_not_of("0123456789") != std::string::npos ||
        pid == std::to_string(::getpid())) continue;
    std::ifstream comm(entry.path() / "comm");
    std::string name;
    std::getline(comm, name);
    if (name == "frontend_dt5730" || name == "WaveDump" || name == "wavedump") {
      throw std::runtime_error("Another DAQ process is active (PID " +
                               pid +
                               "); stop it before recovery");
    }
  }
}

void RecoverDigitizer(const DAQHardwareSettings& settings,
                      const std::atomic<bool>& keep_running,
                      std::ostream& log) {
  const auto check_cancelled = [&]() {
    if (!keep_running.load()) throw std::runtime_error("Recovery cancelled");
  };
  std::unique_ptr<CaenDigitizer> digitizer;
  for (int attempt = 1; attempt <= 3; ++attempt) {
    check_cancelled();
    log << "[Recovery] Connecting to USB link " << settings.connection.link
        << " (attempt " << attempt << "/3)" << std::endl;
    try {
      digitizer = std::make_unique<CaenDigitizer>(
          CAEN_DGTZ_USB, settings.connection.link,
          settings.connection.node, settings.connection.base_address);
      break;
    } catch (const CaenApiError& error) {
      log << "[Recovery] " << error.what() << std::endl;
      const bool transient = error.code() == -24 || error.code() == -1 ||
                             error.code() == -18 || error.code() == -26;
      if (!transient || attempt == 3) {
        throw std::runtime_error(
            "Cannot connect to digitizer; recovery was not performed. "
            "Check device power/USB connection. Last error: " +
            std::string(error.what()));
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
  }
  const int handle = digitizer->GetHandle();
  CAEN_DGTZ_BoardInfo_t before{};
  CAEN_CHECK(CAEN_DGTZ_GetInfo(handle, &before));
  const auto validate = [&](const CAEN_DGTZ_BoardInfo_t& info) {
    if (std::string(info.ModelName).rfind(settings.connection.expected_model, 0) != 0 ||
        info.FamilyCode != CAEN_DGTZ_XX730_FAMILY_CODE ||
        info.ADC_NBits != settings.adc_bits ||
        (settings.connection.has_expected_serial &&
         info.SerialNumber != settings.connection.expected_serial)) {
      throw std::runtime_error("Recovery board identity does not match config");
    }
    const std::string firmware = info.AMC_FirmwareRel;
    std::size_t end = 0;
    const int major = std::stoi(firmware, &end);
    if (end == 0 || major < 0 || major >= 128 ||
        (end < firmware.size() && firmware[end] != '.')) {
      throw std::runtime_error("Recovery requires standard waveform firmware");
    }
  };
  validate(before);
  check_cancelled();
  log << "[Recovery] Verified model=" << before.ModelName
      << ", serial=" << before.SerialNumber << std::endl;
  CAEN_CHECK(CAEN_DGTZ_SWStopAcquisition(handle));
  log << "[Recovery] Acquisition stopped; resetting board and clearing pending events"
      << std::endl;
  check_cancelled();
  digitizer->Reset();
  CAEN_DGTZ_BoardInfo_t after{};
  CAEN_CHECK(CAEN_DGTZ_GetInfo(handle, &after));
  validate(after);
  if (std::string(before.ModelName) != after.ModelName ||
      before.SerialNumber != after.SerialNumber) {
    throw std::runtime_error("Board identity changed across recovery reset");
  }
  CAEN_CHECK(CAEN_DGTZ_ClearData(handle));
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
  unsigned healthy_count = 0;
  uint32_t status_raw = 0, failure_raw = 0;
  do {
    check_cancelled();
    CAEN_CHECK(CAEN_DGTZ_ReadRegister(
        handle, dt5730_status::kAcquisitionStatusRegister, &status_raw));
    CAEN_CHECK(CAEN_DGTZ_ReadRegister(
        handle, dt5730_status::kBoardFailureStatusRegister, &failure_raw));
    const auto status = dt5730_status::DecodeAcquisitionStatus(status_raw);
    const auto failure = dt5730_status::DecodeBoardFailureStatus(failure_raw);
    const bool healthy = !status.run && !status.event_ready && !status.event_full &&
                         !status.HasFatalHealthFault() && !failure.Any();
    healthy_count = healthy ? healthy_count + 1 : 0;
    if (healthy_count >= 3) {
      digitizer->Close();
      log << "[Recovery] SUCCESS: RUN=0, READY=1, PLL=locked, buffer=empty, "
             "fault=0. Start a new DAQ run to reapply the selected configuration."
          << std::endl;
      return;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  } while (std::chrono::steady_clock::now() < deadline);
  throw std::runtime_error("Recovery did not reach healthy idle state: status=" +
                           std::to_string(status_raw) + ", failure=" +
                           std::to_string(failure_raw));
}
