#ifndef CPNR_DIGITIZER_LOCK_H
#define CPNR_DIGITIZER_LOCK_H

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

// Shared by acquisition and recovery. Keep the inode after closing: unlinking
// a flock file would allow a second process to lock a different inode.
class DigitizerLock {
 public:
  explicit DigitizerLock(int link) {
#ifdef CPNR_CAEN_MOCK
    const std::string prefix = "/tmp/cpnr-dt5730-mock-usb-";
#else
    const std::string prefix = "/tmp/cpnr-dt5730-usb-";
#endif
    const std::string path = prefix +
                             std::to_string(link) + ".lock";
    fd_ = ::open(path.c_str(), O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0666);
    if (fd_ < 0) {
      throw std::runtime_error("Cannot open digitizer ownership lock: " +
                               std::string(std::strerror(errno)));
    }
    struct stat info{};
    if (::fstat(fd_, &info) != 0 || !S_ISREG(info.st_mode) ||
        info.st_nlink != 1 || ::flock(fd_, LOCK_EX | LOCK_NB) != 0) {
      ::close(fd_);
      fd_ = -1;
      throw std::runtime_error(
          "Digitizer is busy or its ownership lock is unavailable; "
          "stop the other acquisition/recovery process first");
    }
  }
  ~DigitizerLock() { if (fd_ >= 0) ::close(fd_); }
  DigitizerLock(const DigitizerLock&) = delete;
  DigitizerLock& operator=(const DigitizerLock&) = delete;

 private:
  int fd_ = -1;
};

#endif
