#include "DigitizerRecovery.h"
#include "CaenDigitizer.h"
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace {
void Require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
void MustFail(const std::function<void()>& action, const std::string& text) {
  try { action(); }
  catch (const std::exception& error) {
    Require(std::string(error.what()).find(text) != std::string::npos,
            "unexpected failure reason");
    return;
  }
  throw std::runtime_error("expected failure did not occur");
}
void Clean() {
  caen_mock::state = caen_mock::State{};
  caen_mock::ResetLifecycleInstrumentation();
}
}

int main() {
  try {
    DAQHardwareSettings settings;
    settings.connection.expected_model = "MOCK-DT5730S";
    settings.connection.has_expected_serial = true;
    settings.connection.expected_serial = 5730;
    std::atomic<bool> keep_running{true};
    std::ostringstream log;
    Clean();
    caen_mock::open_failures_remaining = 2;
    caen_mock::state.acquisition_running = true;
    caen_mock::state.pending_events = 20;
    RecoverDigitizer(settings, keep_running, log);
    Require(caen_mock::open_calls == 3 && caen_mock::close_calls == 1,
            "transient -24 must retry and close the successful handle");
    Require(caen_mock::reset_calls == 1 && caen_mock::clear_calls == 1 &&
            !caen_mock::state.acquisition_running && caen_mock::state.pending_events == 0,
            "successful recovery must stop, reset and clear without acquisition");
    Require(log.str().find("SUCCESS") != std::string::npos, "missing success status");

    Clean();
    settings.connection.expected_serial = 999;
    MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "identity");
    Require(caen_mock::reset_calls == 0 && caen_mock::stop_calls == 0 &&
            caen_mock::clear_calls == 0 && caen_mock::close_calls == 1,
            "identity mismatch must close without mutating the board");
    settings.connection.expected_serial = 5730;

    Clean();
    caen_mock::open_failures_remaining = 3;
    MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "not performed");
    Require(caen_mock::reset_calls == 0 && caen_mock::open_calls == 3,
            "persistent open failure must be bounded and never reset");

    Clean();
    {
      CaenDigitizer acquisition(CAEN_DGTZ_USB, 0, 0, 0);
      MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "busy");
      Require(caen_mock::open_calls == 1 && caen_mock::reset_calls == 0,
              "active ownership must block recovery before any CAEN call");
    }
    Clean();
    caen_mock::state.board_not_ready_fault = true;
    MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "healthy idle");
    Require(caen_mock::close_calls == 1, "health failure leaked handle");

    Clean();
    caen_mock::reset_should_fail = true;
    MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "error code");
    Require(caen_mock::close_calls == 1, "reset failure leaked handle");

    Clean();
    keep_running = false;
    MustFail([&] { RecoverDigitizer(settings, keep_running, log); }, "cancelled");
    Require(caen_mock::open_calls == 0, "cancelled recovery opened device");
    std::cout << "Digitizer recovery tests passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
