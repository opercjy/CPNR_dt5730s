#include "DAQManager.h"
#include <iostream>
#include <fstream>
#include <getopt.h>
#include <csignal>
#include <iomanip>
#include <atomic>

// 스레드 안전한 종료 플래그
std::atomic<bool> g_is_running{true};

void sig_handler(int) {
    std::cout << "\n\033[1;33m[Interrupt] Catching Signal. Stopping DAQ Gracefully...\033[0m\n";
    g_is_running = false; // 플래그만 false로 변경
}

void PrintConfigContent(const std::string& filepath) {
    std::ifstream file(filepath);
    if (!file.is_open()) return;
    std::cout << "\n\033[1;36m=== [ Config Details : " << filepath << " ] ===\033[0m\n";
    std::string line;
    while (std::getline(file, line)) {
        std::cout << "  " << line << "\n";
    }
    std::cout << "\033[1;36m====================================================\033[0m\n\n";
}

int main(int argc, char** argv) {
    std::string config_file = "config/dt5730s_inorganic.conf";
    std::string output_file = "../data/data_run.dat";
    int max_events = 0;       
    int run_time_sec = 0;     

    // 🚀 다중 프로세스 듀얼 제어용 식별 변수 추가
    int link_num = 0;
    int zmq_port = 5555;

    int opt;
    // 🚀 getopt 파서에 l(USB 링크)과 p(ZMQ 포트) 옵션 추가
    while ((opt = getopt(argc, argv, "c:o:n:t:l:p:h")) != -1) {
        switch (opt) {
            case 'c': config_file = optarg; break;
            case 'o': output_file = optarg; break;
            case 'n': max_events = std::stoi(optarg); break;
            case 't': run_time_sec = std::stoi(optarg); break;
            case 'l': link_num = std::stoi(optarg); break;
            case 'p': zmq_port = std::stoi(optarg); break;
            case 'h':
            default:
                std::cout << "Usage: " << argv[0] << " -c <config> [-o <out.dat>] [-n <events>] [-t <sec>] [-l <usb_link>] [-p <zmq_port>]\n";
                return 1;
        }
    }

    std::signal(SIGINT, sig_handler);
    std::signal(SIGTERM, sig_handler);

    try {
        PrintConfigContent(config_file);
        auto t = std::time(nullptr);
        auto tm = *std::localtime(&t);
        
        // 🚀 기존 시스템 부팅 로깅 완벽 보존 및 링크/포트 정보 병합
        std::cout << "\033[1;32m[Frontend] System Boot Time : \033[0m" << std::put_time(&tm, "%Y-%m-%d %H:%M:%S") << "\n"
                  << "\033[1;34m[Frontend] Output Target    : \033[0m" << output_file << "\n"
                  << "\033[1;35m[Frontend] USB Link / ZMQ   : \033[0mBoard " << link_num << " / Port " << zmq_port << "\n";

        // 🚀 DAQManager에 6개의 인자 모두 전달
        DAQManager daq(config_file, output_file, max_events, run_time_sec, link_num, zmq_port);
        
        // 메인 루프에 플래그 전달
        daq.Start(g_is_running);

    } catch (const std::exception& e) {
        std::cerr << "\n\033[1;31m[Fatal Error]\033[0m " << e.what() << "\n";
        return 1;
    }
    return 0;
}
