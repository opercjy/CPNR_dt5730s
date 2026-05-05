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

    int opt;
    while ((opt = getopt(argc, argv, "c:o:n:t:")) != -1) {
        switch (opt) {
            case 'c': config_file = optarg; break;
            case 'o': output_file = optarg; break;
            case 'n': max_events = std::stoi(optarg); break;
            case 't': run_time_sec = std::stoi(optarg); break;
        }
    }

    std::signal(SIGINT, sig_handler);
    std::signal(SIGTERM, sig_handler);

    try {
        PrintConfigContent(config_file);
        auto t = std::time(nullptr);
        auto tm = *std::localtime(&t);
        std::cout << "\033[1;32m[Frontend] System Boot Time : \033[0m" << std::put_time(&tm, "%Y-%m-%d %H:%M:%S") << "\n"
                  << "\033[1;34m[Frontend] Output Target    : \033[0m" << output_file << "\n";

        DAQManager daq(config_file, output_file, max_events, run_time_sec);
        
        // 메인 루프에 플래그 전달
        daq.Start(g_is_running);

    } catch (const std::exception& e) {
        std::cerr << "\n\033[1;31m[Fatal Error]\033[0m " << e.what() << "\n";
        return 1;
    }
    return 0;
}