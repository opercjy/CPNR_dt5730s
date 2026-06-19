#ifndef DAQMANAGER_H
#define DAQMANAGER_H

#include "ConfigParser.h"
#include "CaenDigitizer.h"
#include <string>
#include <atomic>
#include <fstream>
#include <vector>

#define MAX_DT5730_CH 8

class DAQManager {
public:
    // USB 링크(link_num)와 ZMQ 포트(zmq_port) 동적 할당 생성자
    DAQManager(const std::string &config_file, const std::string &output_file,
               int max_events, int run_time_sec, int link_num = 0, int zmq_port = 5555);
    ~DAQManager();

    void Start(std::atomic<bool>& is_running);
    void Stop();

private:
    void SetupHardware();
    void AcquisitionLoop(std::atomic<bool>& is_running);

    ConfigParser config_;
    std::string output_file_;
    int max_events_;
    int run_time_sec_;
    
    // 다중 프로세스 제어를 위한 식별 변수
    int link_num_;
    int zmq_port_;

    std::atomic<bool> running_;
    CaenDigitizer digitizer_;
    std::ofstream out_stream_;
    std::vector<char> raw_buffer_pool_;
    
    uint32_t current_sample_rate_ps_;
    
    void* zmq_ctx_;
    void* zmq_pub_;
};

#endif // DAQMANAGER_H
