#ifndef CPNR_DIGITIZER_RECOVERY_H
#define CPNR_DIGITIZER_RECOVERY_H

#include "DAQConfig.h"
#include <atomic>
#include <iosfwd>

// Resets acquisition configuration and discards only the device's volatile
// event buffer. No acquisition, run files, firmware or host USB reset.
void RecoverDigitizer(const DAQHardwareSettings& settings,
                      const std::atomic<bool>& keep_running,
                      std::ostream& log);
void RefuseRecoveryWithLegacyFrontend();

#endif
