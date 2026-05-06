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

// ==============================================================================
// [시스템] Graceful Shutdown을 위한 시그널 핸들러 (원본 보존)
// ==============================================================================
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
    // (원본 보존) 다양한 커맨드라인 옵션 지원
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

    // (원본 보존) 출력 파일명 자동 생성
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

    // (원본 보존) 고속 I/O를 위한 4MB 버퍼링
    std::ifstream ifs;
    std::vector<char> read_buffer(4 * 1024 * 1024);
    ifs.rdbuf()->pubsetbuf(read_buffer.data(), read_buffer.size());
    
    ifs.open(input_file, std::ios::binary);
    if (!ifs.is_open()) {
        std::cerr << "[Error] Cannot open input file: " << input_file << "\n";
        return 1;
    }

    // (원본 보존) 진행률(ETA) 계산을 위한 전체 파일 사이즈 획득
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
    
    // 트리 브랜치 변수
    uint32_t record_len_branch = 0; // [NEW] 레코드 길이 메타데이터 저장용
    std::vector<uint16_t> wave_ch[MAX_CH];
    double charge_ch[MAX_CH] = {0.0};
    double pulse_start_time_ch[MAX_CH] = {0.0}; 
    double baseline_ch[MAX_CH] = {0.0}; // [NEW] 베이스라인 값 저장용

    if (debug_event_id < 0) {
        fOut = new TFile(output_file.c_str(), "RECREATE");
        
        // (원본 보존) .conf 설정 파일을 ROOT 파일 내부에 메타데이터로 통째로 저장
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
        tOut->Branch("SyncTime_TTT", &header.ExtendedTTT, "SyncTime_TTT/l");
        tOut->Branch("ChannelMask", &header.ChannelMask, "ChannelMask/s");
        tOut->Branch("RecordLength", &record_len_branch, "RecordLength/i"); // [NEW]

        for (int i = 0; i < MAX_CH; ++i) {
            tOut->Branch(Form("Charge_CH%d", i), &charge_ch[i], Form("Charge_CH%d/D", i));
            tOut->Branch(Form("PulseStart_T0_CH%d", i), &pulse_start_time_ch[i], Form("PulseStart_T0_CH%d/D", i));
            tOut->Branch(Form("Baseline_CH%d", i), &baseline_ch[i], Form("Baseline_CH%d/D", i)); // [NEW]
            
            if (save_waveform) {
                tOut->Branch(Form("Waveform_CH%d", i), &wave_ch[i]);
            }
        }
    }

    std::vector<uint16_t> raw_waveform_buffer;
    uint32_t current_event = 0;
    auto start_time = std::chrono::steady_clock::now();
    
    std::cout << "\033[1;32m[Production] Starting Universal Conversion...\033[0m\n";

    while (g_running && ifs.read(reinterpret_cast<char *>(&header), sizeof(EventHeader))) {
        processed_bytes += sizeof(EventHeader);
        current_event++;
        record_len_branch = header.RecordLength; // 헤더에서 동적 길이 추출

        int active_ch = 0;
        for (int i = 0; i < MAX_CH; ++i) {
            if ((header.ChannelMask >> i) & 1) active_ch++;
            wave_ch[i].clear();
            charge_ch[i] = 0.0;
            pulse_start_time_ch[i] = -1.0;
            baseline_ch[i] = 0.0;
        }

        size_t wave_len = header.RecordLength * active_ch;
        size_t wave_bytes_size = wave_len * sizeof(uint16_t);

        // (원본 보존) 고속 메모리 포인터 접근을 위한 단일 버퍼 리드
        raw_waveform_buffer.resize(wave_len);
        ifs.read(reinterpret_cast<char *>(raw_waveform_buffer.data()), wave_bytes_size);
        processed_bytes += wave_bytes_size;

        int offset = 0;
        for (int ch = 0; ch < MAX_CH; ++ch) {
            if ((header.ChannelMask >> ch) & 1) {
                uint16_t* trace_ptr = raw_waveform_buffer.data() + offset;
                size_t trace_len = header.RecordLength;

                // 🌟 [제1원리 통합] 메타데이터 기반 동적 베이스라인 (25%, 최대 150 샘플 방어)
                if (trace_len > 0) {
                    size_t baseline_samples = std::min((size_t)150, (size_t)(trace_len * 0.25));
                    
                    double baseline = 0.0;
                    for(size_t i = 0; i < baseline_samples; ++i) {
                        baseline += trace_ptr[i];
                    }
                    baseline /= baseline_samples;
                    baseline_ch[ch] = baseline;

                    // 1. Charge 적분 (음극성)
                    double charge = 0.0;
                    for(size_t i = baseline_samples; i < trace_len; ++i) {
                        if (trace_ptr[i] < baseline) {
                            charge += (baseline - trace_ptr[i]);
                        }
                    }
                    charge_ch[ch] = (charge > 0) ? charge : 0.0;

                    // 2. Micro-Time (T0) 탐색 (Baseline - 30.0 트리거)
                    double trigger_threshold = baseline - 30.0; 
                    for(size_t i = baseline_samples; i < trace_len; ++i) {
                        if (trace_ptr[i] < trigger_threshold) {
                            pulse_start_time_ch[ch] = i * 2.0; // 2ns per sample
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

        // (원본 보존) 정밀 ETA 및 네트워크 속도 스타일의 진행률 표시
        if (current_event % 2000 == 0) {
            auto now = std::chrono::steady_clock::now();
            double elapsed_sec = std::chrono::duration_cast<std::chrono::duration<double>>(now - start_time).count();
            double progress = (static_cast<double>(processed_bytes) / total_bytes) * 100.0;
            double speed_bps = processed_bytes / elapsed_sec; 
            double eta_sec = (total_bytes - processed_bytes) / speed_bps;

            std::cout << "\r\033[K" << "[Progress] " 
                      << std::fixed << std::setprecision(1) << progress << "% | "
                      << "Events: " << current_event << " | "
                      << "Speed: " << std::setprecision(1) << (speed_bps / 1024.0 / 1024.0) << " MB/s | "
                      << "ETA: " << (int)eta_sec << " s" << std::flush;
        }

        // 🌟 (원본 + 개선) 인터랙티브 디버거 모드 (베이스라인 시각화 추가)
        if (debug_event_id >= 0 && (int)header.EventID == debug_event_id && active_ch > 0) {
            int disp_ch = 0;
            for (; disp_ch < MAX_CH; ++disp_ch) {
                if ((header.ChannelMask >> disp_ch) & 1) break;
            }
            std::vector<double> x(header.RecordLength), y(header.RecordLength);
            for (size_t i = 0; i < header.RecordLength; ++i) {
                x[i] = i * 2.0; // 시간(ns) 변환
                y[i] = wave_ch[disp_ch][i];
            }
            TGraph *gr = new TGraph(header.RecordLength, x.data(), y.data());
            gr->SetTitle(Form("Event %d (CH%d) - Charge: %.1f, T0: %.1f ns;Time (ns);ADC Value", 
                              debug_event_id, disp_ch, charge_ch[disp_ch], pulse_start_time_ch[disp_ch]));
            gr->SetLineColor(kBlue);
            gr->SetLineWidth(2);
            gr->Draw("AL");

            // 베이스라인 시각적 확인 (빨간 점선)
            TGraph* bl_line = new TGraph(2);
            bl_line->SetPoint(0, 0, baseline_ch[disp_ch]);
            bl_line->SetPoint(1, header.RecordLength * 2.0, baseline_ch[disp_ch]);
            bl_line->SetLineColor(kRed);
            bl_line->SetLineStyle(2);
            bl_line->SetLineWidth(2);
            bl_line->Draw("L SAME");

            c1->Update();
            std::cout << "\n\n\033[1;33m[Debugger] Displaying Event " << debug_event_id << " CH" << disp_ch << "\033[0m";
            std::cout << "\nRecordLength: " << header.RecordLength << " | Baseline: " << baseline_ch[disp_ch] << "\n";
            std::cout << "\033[1;32m(Close the TCanvas window or press Ctrl+C in terminal to exit)\033[0m\n";
            app->Run(true);
            break; 
        }
    }

    if (g_running && debug_event_id < 0) {
        std::cout << "\r\033[K[Progress] 100.0% | Events: " << current_event << " | Done.          \n";
    }

    if (fOut) {
        fOut->Write();
        fOut->Close();
        delete fOut;
        std::cout << "\033[1;32m[Production] Conversion complete. Saved to \033[0m" << output_file << "\n";
    }

    if (app) delete app;
    return 0;
}
