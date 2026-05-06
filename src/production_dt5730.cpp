#include "EventHeader.h"
#include <TApplication.h>
#include <TCanvas.h>
#include <TFile.h>
#include <TGraph.h>
#include <TTree.h>
#include <TMacro.h>
#include <TParameter.h>
#include <TDatime.h>
#include <fstream>
#include <getopt.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <chrono>
#include <csignal>
#include <numeric>

#ifdef __ROOTCLING__
#pragma link C++ class std::vector<uint16_t>+;
#endif

volatile std::sig_atomic_t g_running = 1;

void sig_handler(int) {
    std::cout << "\n\033[1;33m[Interrupt] Received stop signal. Saving ROOT file gracefully...\033[0m\n";
    g_running = 0;
}

int main(int argc, char **argv) {
    std::string input_file = "";
    std::string output_file = "";
    std::string config_file = ""; 
    int debug_event_id = -1;
    int run_number = 0;
    bool save_waveform = false; 

    int opt;
    while ((opt = getopt(argc, argv, "i:o:c:r:d:w")) != -1) {
        switch (opt) {
            case 'i': input_file = optarg; break;
            case 'o': output_file = optarg; break;
            case 'c': config_file = optarg; break;
            case 'r': run_number = std::stoi(optarg); break;
            case 'd': debug_event_id = std::stoi(optarg); break;
            case 'w': save_waveform = true; break;
        }
    }

    if (input_file.empty() && optind < argc) input_file = argv[optind];
    if (input_file.empty()) {
        std::cerr << "Usage: " << argv[0] << " [input.dat] [-o output.root] [-c config.conf] [-r run_number] [-d event_id] [-w]\n";
        return 1;
    }

    if (output_file.empty() && debug_event_id < 0) {
        size_t last_dot = input_file.find_last_of(".");
        size_t last_slash = input_file.find_last_of("/\\");
        if (last_dot == std::string::npos || (last_slash != std::string::npos && last_dot < last_slash)) {
            output_file = input_file + "_prod.root";
        } else {
            output_file = input_file.substr(0, last_dot) + "_prod.root";
        }
    }

    std::signal(SIGINT, sig_handler);
    std::signal(SIGTERM, sig_handler);

    std::ifstream ifs;
    std::vector<char> read_buffer(4 * 1024 * 1024);
    ifs.rdbuf()->pubsetbuf(read_buffer.data(), read_buffer.size());
    
    ifs.open(input_file, std::ios::binary);
    if (!ifs.is_open()) return 1;

    ifs.seekg(0, std::ios::end);
    size_t total_bytes = ifs.tellg();
    ifs.seekg(0, std::ios::beg);
    size_t processed_bytes = 0;

    TApplication *app = nullptr;
    TCanvas *c1 = nullptr;
    if (debug_event_id >= 0) {
        app = new TApplication("App", &argc, argv);
        c1 = new TCanvas("c1", "Interactive Debugger", 1000, 600);
    }

    TFile *fOut = nullptr;
    TTree *tOut = nullptr;
    EventHeader header;
    
    std::vector<uint16_t> wave_ch[MAX_CH];
    double charge_ch[MAX_CH] = {0.0};
    
    // [NEW] 펄스의 미세 도착 시간 (Micro-time)
    double pulse_start_time_ch[MAX_CH] = {0.0}; 

    if (debug_event_id < 0) {
        fOut = new TFile(output_file.c_str(), "RECREATE");
        
        if (!config_file.empty()) {
            std::ifstream cfs(config_file);
            if (cfs.is_open()) {
                TMacro config_macro(config_file.c_str());
                config_macro.Write("RunConfig");
            }
        }
        
        TParameter<int> p_run_num("RunNumber", run_number);
        p_run_num.Write();

        tOut = new TTree("phys_tree", "DT5730 Physics Data");
        tOut->Branch("EventID", &header.EventID, "EventID/i");
        
        // [1] 거시적 시간 (Macro Time): 장비 클록이 찍힌 절대 동기화 시간
        tOut->Branch("SyncTime_TTT", &header.ExtendedTTT, "SyncTime_TTT/l");
        tOut->Branch("ChannelMask", &header.ChannelMask, "ChannelMask/s");
        
        for (int i = 0; i < MAX_CH; ++i) {
            tOut->Branch(Form("Charge_CH%d", i), &charge_ch[i], Form("Charge_CH%d/D", i));
            
            // [2] 미시적 시간 (Micro Time): 파형 내부에서 펄스가 하강을 시작한 정밀 상대 시간 (ns)
            tOut->Branch(Form("PulseStart_T0_CH%d", i), &pulse_start_time_ch[i], Form("PulseStart_T0_CH%d/D", i));
            
            if (save_waveform) {
                tOut->Branch(Form("Waveform_CH%d", i), &wave_ch[i]);
            }
        }
    }

    std::vector<uint16_t> raw_waveform_buffer;
    uint32_t current_event = 0;
    auto start_time = std::chrono::steady_clock::now();
    
    std::cout << "\033[1;32m[Production] Starting conversion...\033[0m\n";

    while (g_running && ifs.read(reinterpret_cast<char *>(&header), sizeof(EventHeader))) {
        processed_bytes += sizeof(EventHeader);
        current_event++;

        int active_ch = 0;
        for (int i = 0; i < MAX_CH; ++i) {
            if ((header.ChannelMask >> i) & 1) active_ch++;
            wave_ch[i].clear();
            charge_ch[i] = 0.0;
            pulse_start_time_ch[i] = 0.0;
        }

        size_t wave_len = header.RecordLength * active_ch;
        size_t wave_bytes_size = wave_len * sizeof(uint16_t);

        raw_waveform_buffer.resize(wave_len);
        ifs.read(reinterpret_cast<char *>(raw_waveform_buffer.data()), wave_bytes_size);
        processed_bytes += wave_bytes_size;

        int offset = 0;
        for (int ch = 0; ch < MAX_CH; ++ch) {
            if ((header.ChannelMask >> ch) & 1) {
                uint16_t* trace_ptr = raw_waveform_buffer.data() + offset;
                size_t trace_len = header.RecordLength;

                if (trace_len > 200) {
                    // 유동적 베이스라인 (앞 25% 공간 활용)
                    size_t baseline_samples = trace_len / 4;
                    double baseline = 0.0;
                    for(size_t i = 0; i < baseline_samples; ++i) baseline += trace_ptr[i];
                    baseline /= baseline_samples;

                    // 1. Charge 적분
                    double charge = 0.0;
                    for(size_t i = baseline_samples; i < trace_len; ++i) {
                        charge += (baseline - trace_ptr[i]);
                    }
                    charge_ch[ch] = (charge > 0) ? charge : 0.0;

                    // 2. [핵심] Micro-Time (T0) 탐색 알고리즘
                    // 노이즈 플럭추에이션을 피하기 위해 베이스라인에서 30 Bin 아래로 뚫린 지점을 진짜 시작점(T0)으로 간주
                    double trigger_threshold = baseline - 30.0; 
                    for(size_t i = baseline_samples; i < trace_len; ++i) {
                        if (trace_ptr[i] < trigger_threshold) {
                            // DT5730S는 500MS/s 이므로 1 Sample = 2 ns
                            pulse_start_time_ch[ch] = i * 2.0; 
                            break;
                        }
                    }
                }

                if (save_waveform || (debug_event_id >= 0 && (int)header.EventID == debug_event_id)) {
                    wave_ch[ch].assign(trace_ptr, trace_ptr + trace_len);
                }
                offset += trace_len;
            }
        }

        if (tOut) tOut->Fill();

        if (current_event % 1000 == 0) {
            auto now = std::chrono::steady_clock::now();
            double elapsed_sec = std::chrono::duration_cast<std::chrono::duration<double>>(now - start_time).count();
            double progress = (static_cast<double>(processed_bytes) / total_bytes) * 100.0;
            double speed_bps = processed_bytes / elapsed_sec; 
            double eta_sec = (total_bytes - processed_bytes) / speed_bps;

            std::cout << "\r\033[K" << "[Progress] " 
                      << std::fixed << std::setprecision(1) << progress << "% | "
                      << "Events: " << current_event << " | "
                      << "ETA: " << (int)eta_sec << " s" << std::flush;
        }

        if (debug_event_id >= 0 && (int)header.EventID == debug_event_id && active_ch > 0) {
            int disp_ch = 0;
            for (; disp_ch < MAX_CH; ++disp_ch) {
                if ((header.ChannelMask >> disp_ch) & 1) break;
            }
            std::vector<double> x(header.RecordLength), y(header.RecordLength);
            for (size_t i = 0; i < header.RecordLength; ++i) {
                x[i] = i;
                y[i] = wave_ch[disp_ch][i];
            }
            TGraph *gr = new TGraph(header.RecordLength, x.data(), y.data());
            gr->SetTitle(Form("Event %d (CH%d) - Charge: %.1f, T0: %.1f ns;Sample Index;ADC Value", 
                              debug_event_id, disp_ch, charge_ch[disp_ch], pulse_start_time_ch[disp_ch]));
            gr->SetLineColor(kBlue);
            gr->Draw("AL");
            c1->Update();
            std::cout << "\n[Debugger] Displaying Event " << debug_event_id << " CH" << disp_ch << " (Close window to exit)\n";
            app->Run(true);
            break; 
        }
    }

    if (g_running) {
        std::cout << "\r\033[K[Progress] 100.0% | Events: " << current_event << " | Done.          \n";
    }

    if (fOut) {
        fOut->Write();
        fOut->Close();
        delete fOut;
        std::cout << "\033[1;32m[Production] Conversion complete. Saved to \033[0m" << output_file << "\n";
    }

    return 0;
}