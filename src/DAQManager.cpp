#include "DAQManager.h"
#include "EventHeader.h"
#include "CAENComm.h" 

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <iomanip>
#include <ctime>
#include <thread>
#include <zmq.h>
#include <filesystem>
#include <stdexcept>

DAQManager::DAQManager(const std::string &config_file,
                       const std::string &output_file, int max_events,
                       int run_time_sec, int link_num, int zmq_port)
    : config_(config_file), output_file_(output_file), max_events_(max_events),
      run_time_sec_(run_time_sec), link_num_(link_num), zmq_port_(zmq_port), running_(false),
      digitizer_(CAEN_DGTZ_USB, link_num, 0, 0) {
        
  // [ZMQ Pub Socket 다중 포트 바인딩]
  zmq_ctx_ = zmq_ctx_new();
  zmq_pub_ = zmq_socket(zmq_ctx_, ZMQ_PUB);
  int hwm = 5000;
  zmq_setsockopt(zmq_pub_, ZMQ_SNDHWM, &hwm, sizeof(hwm));
  int linger = 1000;
  zmq_setsockopt(zmq_pub_, ZMQ_LINGER, &linger, sizeof(linger));
  
  std::string tcp_addr = "tcp://127.0.0.1:" + std::to_string(zmq_port_);
  if (zmq_bind(zmq_pub_, tcp_addr.c_str()) != 0) {
      std::cerr << "\033[1;31m[Fatal Error] Failed to bind ZMQ port: " << zmq_port_ << "\033[0m\n";
  }

  // [Output File & 4MB Buffer 초기화 보존]
  if (!output_file_.empty()) {
    std::filesystem::path p(output_file_);
    if (p.has_parent_path()) {
        std::filesystem::create_directories(p.parent_path());
    }
    // 프로세스별 독립된 4MB 파일 버퍼 할당
    write_buffer_.resize(4 * 1024 * 1024); 
    out_stream_.rdbuf()->pubsetbuf(write_buffer_.data(), write_buffer_.size());
    out_stream_.open(output_file_, std::ios::binary);
    if (!out_stream_.is_open()) {
      throw std::runtime_error("Cannot open output file: " + output_file_);
    }
  }
  
  SetupHardware();
}

DAQManager::~DAQManager() {
  Stop();
  if (out_stream_.is_open()) out_stream_.close();
  zmq_close(zmq_pub_);
  zmq_ctx_destroy(zmq_ctx_);
}

void DAQManager::SetupHardware() {
  std::cout << "\033[1;36m[DAQManager B" << link_num_ << "]\033[0m Configuring Hardware from Config...\n";
  int handle = digitizer_.GetHandle();
  
  uint32_t record_length = config_.GetInt("Digitizer", "RecordLength", 4096);
  uint32_t channel_mask = config_.GetInt("Digitizer", "ChannelMask", 0xFF);
  uint32_t post_trigger = config_.GetInt("Digitizer", "PostTrigger", 80);

  CAEN_CHECK(CAEN_DGTZ_SetRecordLength(handle, record_length));
  CAEN_CHECK(CAEN_DGTZ_SetChannelEnableMask(handle, channel_mask));
  CAEN_CHECK(CAEN_DGTZ_SetPostTriggerSize(handle, post_trigger));

  // DT4700 외부 클럭/트리거 연동을 위한 동기화 모드 추가
  int sync_mode = config_.GetInt("Synchronization", "RunSyncMode", 0);
  if (sync_mode == 1) {
      CAEN_CHECK(CAEN_DGTZ_SetRunSynchronizationMode(handle, CAEN_DGTZ_RUN_SYNC_TrgOutTrgInDaisyChain));
  } else {
      CAEN_CHECK(CAEN_DGTZ_SetRunSynchronizationMode(handle, CAEN_DGTZ_RUN_SYNC_Disabled));
  }

  int pol_val = config_.GetInt("Digitizer", "TriggerPolarity", 1);

  for (int ch = 0; ch < MAX_CH; ++ch) {
      if ((channel_mask >> ch) & 1) {
          std::string ch_sec = "Channel_" + std::to_string(ch);
          uint32_t offset = config_.GetInt(ch_sec, "DCOffset", 7050);
          uint32_t thr = config_.GetInt(ch_sec, "TriggerThreshold", 15000);
          
          if (thr > 16383) thr = 16383; // 14-bit DT5730 해상도 예외 방어

          CAEN_CHECK(CAEN_DGTZ_SetChannelDCOffset(handle, ch, offset));
          CAEN_CHECK(CAEN_DGTZ_SetTriggerPolarity(handle, ch, (pol_val == 0) ? CAEN_DGTZ_TriggerOnRisingEdge : CAEN_DGTZ_TriggerOnFallingEdge));
          CAEN_CHECK(CAEN_DGTZ_SetChannelTriggerThreshold(handle, ch, thr));
      }
  }

  // 획득 모드 및 외부/내부 트리거 설정
  CAEN_DGTZ_TriggerMode_t trg_mode = CAEN_DGTZ_TRGMODE_ACQ_ONLY;
  
  int ext_trg = config_.GetInt("Digitizer", "ExtTriggerMode", 1);
  if (ext_trg > 0) CAEN_CHECK(CAEN_DGTZ_SetExtTriggerInputMode(handle, trg_mode));
  else CAEN_CHECK(CAEN_DGTZ_SetExtTriggerInputMode(handle, CAEN_DGTZ_TRGMODE_DISABLED));
  
  int self_trg = config_.GetInt("Digitizer", "SelfTriggerMode", 1);
  if (self_trg > 0) CAEN_CHECK(CAEN_DGTZ_SetChannelSelfTrigger(handle, trg_mode, channel_mask));
  else CAEN_CHECK(CAEN_DGTZ_SetChannelSelfTrigger(handle, CAEN_DGTZ_TRGMODE_DISABLED, 0xFF));

  CAEN_CHECK(CAEN_DGTZ_SetSWTriggerMode(handle, trg_mode));
  CAEN_CHECK(CAEN_DGTZ_SetAcquisitionMode(handle, CAEN_DGTZ_SW_CONTROLLED));

  std::cout << "\033[1;36m[FPGA Trigger B" << link_num_ << "]\033[0m Standard OR Logic (Software Coincidence Ready).\n";

  digitizer_.AllocateBuffers();
  
  size_t max_safe_size = sizeof(EventHeader) + (record_length + 1024) * sizeof(uint16_t) * MAX_CH;
  raw_buffer_pool_.resize(max_safe_size);
}

void DAQManager::Start(std::atomic<bool>& is_running) {
  std::cout << "\033[1;32m[DAQManager B" << link_num_ << "]\033[0m Starting Acquisition (ZMQ: " << zmq_port_ << ")...\n";
  CAEN_CHECK(CAEN_DGTZ_SWStartAcquisition(digitizer_.GetHandle()));
  AcquisitionLoop(is_running);
}

void DAQManager::Stop() {
  running_ = false;
}

void DAQManager::AcquisitionLoop(std::atomic<bool>& is_running) {
  EventHeader *header = reinterpret_cast<EventHeader *>(raw_buffer_pool_.data());
  uint16_t *wave_dest = reinterpret_cast<uint16_t *>(raw_buffer_pool_.data() + sizeof(EventHeader));
  
  int handle = digitizer_.GetHandle();
  char *caen_buffer = digitizer_.GetReadoutBuffer();
  CAEN_DGTZ_UINT16_EVENT_t *caen_event = digitizer_.GetDecodedEvent();
  
  uint32_t event_count = 0;
  uint32_t prev_ttt = 0;
  uint64_t ttt_rollovers = 0;
  const uint32_t TTT_MASK = 0x7FFFFFFF;

  // 데드타임 역산 변수
  uint64_t first_ttt_val = 0;
  uint64_t last_ttt_val = 0;
  bool is_first_event = true;
  const double TTT_RESOLUTION_NS = 2.0; // DT5730은 500MS/s 이므로 2.0ns

  auto start_time = std::chrono::steady_clock::now();
  auto last_log_time = start_time;
  uint32_t log_events = 0;
  uint32_t zmq_drops = 0;
  size_t total_bytes_written = 0; 
  size_t last_bytes_written = 0; 
  bool auto_stopped = false;

  while (is_running) {
    if (max_events_ > 0 && (int)event_count >= max_events_) { auto_stopped = true; break; }
    if (run_time_sec_ > 0) {
      auto now = std::chrono::steady_clock::now();
      if (std::chrono::duration_cast<std::chrono::seconds>(now - start_time).count() >= run_time_sec_) {
        auto_stopped = true; break;
      }
    }

    try {
      uint32_t bsize = 0;
      CAEN_CHECK(CAEN_DGTZ_ReadData(handle, CAEN_DGTZ_SLAVE_TERMINATED_READOUT_MBLT, caen_buffer, &bsize));
      if (bsize == 0) {
          std::this_thread::sleep_for(std::chrono::microseconds(500));
          continue; 
      }

      uint32_t num_events = 0;
      CAEN_CHECK(CAEN_DGTZ_GetNumEvents(handle, caen_buffer, bsize, &num_events));

      for (uint32_t i = 0; i < num_events; ++i) {
        CAEN_DGTZ_EventInfo_t evt_info;
        char *evt_ptr = nullptr;
        
        CAEN_CHECK(CAEN_DGTZ_GetEventInfo(handle, caen_buffer, bsize, i, &evt_info, &evt_ptr));
        CAEN_CHECK(CAEN_DGTZ_DecodeEvent(handle, evt_ptr, (void **)&caen_event));

        uint32_t current_ttt = evt_info.TriggerTimeTag & TTT_MASK;
        if (current_ttt < prev_ttt) ttt_rollovers++;
        prev_ttt = current_ttt;

        uint32_t actual_trace_size = 0;
        for (int ch = 0; ch < MAX_CH; ++ch) {
            if ((evt_info.ChannelMask >> ch) & 1) {
                actual_trace_size = caen_event->ChSize[ch];
                break; 
            }
        }

        std::memset(header, 0, sizeof(EventHeader));
        header->ExtendedTTT = (ttt_rollovers << 31) | current_ttt;
        header->EventID = event_count++;
        header->RecordLength = actual_trace_size; 
        header->ChannelMask = evt_info.ChannelMask;
        header->Pattern = evt_info.Pattern;
        header->SampleRate_ps = 2000; 

        if (is_first_event) {
            first_ttt_val = header->ExtendedTTT;
            is_first_event = false;
        }
        last_ttt_val = header->ExtendedTTT;

        size_t payload_size = sizeof(EventHeader);
        for (int ch = 0; ch < MAX_CH; ++ch) {
          if ((header->ChannelMask >> ch) & 1) {
            uint16_t *wave_src = caen_event->DataChannel[ch];
            uint32_t trace_size = caen_event->ChSize[ch];
            
            if (trace_size == 0) continue;

            if (payload_size + trace_size * sizeof(uint16_t) > raw_buffer_pool_.size()) break; 

            std::memcpy(wave_dest + (payload_size - sizeof(EventHeader)) / sizeof(uint16_t),
                        wave_src, trace_size * sizeof(uint16_t));
            
            payload_size += trace_size * sizeof(uint16_t);
          }
        }

        if (out_stream_.is_open()) {
            out_stream_.write(raw_buffer_pool_.data(), payload_size);
            total_bytes_written += payload_size; 
        }
        
        if (zmq_send(zmq_pub_, "DATA", 4, ZMQ_SNDMORE) >= 0) {
            if (zmq_send(zmq_pub_, raw_buffer_pool_.data(), payload_size, ZMQ_DONTWAIT) < 0) {
                if (zmq_errno() == EAGAIN) zmq_drops++;
            }
        }
        log_events++;
      }
    } catch (const std::exception& e) {
        std::cerr << "\n\033[1;33m[Warning] Readout Soft-Error on Link " << link_num_ << ": \033[0m" << e.what() << "\n";
    }

    auto now = std::chrono::steady_clock::now();
    double elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_log_time).count();
    
    if (elapsed_ms >= 1000.0) {
      double rate = (log_events / elapsed_ms) * 1000.0;
      double speed_mbps = ((total_bytes_written - last_bytes_written) / 1048576.0) / (elapsed_ms / 1000.0);
      last_bytes_written = total_bytes_written;

      auto total_sec = std::chrono::duration_cast<std::chrono::seconds>(now - start_time).count();
      int mins = total_sec / 60;
      int secs = total_sec % 60;

      // 보드 번호별로 터미널 색상 구분 (0번: 초록색, 1번: 자주색)
      std::string color = (link_num_ == 0) ? "\033[1;32m" : "\033[1;35m";

      std::cout << "\r\033[K" << color << "[LIVE DAQ B" << link_num_ << "]\033[0m "
                << "Time: \033[1m" << std::setfill('0') << std::setw(2) << mins << ":" << std::setw(2) << secs << "\033[0m | "
                << "Events: \033[1;33m" << event_count << "\033[0m | "
                << "Trg Rate: \033[1;35m" << std::fixed << std::setprecision(1) << rate << " Hz\033[0m | "
                << "Speed: \033[1;32m" << std::fixed << std::setprecision(2) << speed_mbps << " MB/s\033[0m | "
                << "Drops: " << zmq_drops
                << std::flush;
        
      log_events = 0;
      zmq_drops = 0;
      last_log_time = now;

      // 파이썬 관제탑에 STAT 전송
      uint32_t board_temp = 0;
      CAEN_DGTZ_ReadTemperature(handle, 0, &board_temp);
      std::string stat_payload = "{\"temp\":" + std::to_string(board_temp) + "}";
      zmq_send(zmq_pub_, "STAT", 4, ZMQ_SNDMORE);
      zmq_send(zmq_pub_, stat_payload.c_str(), stat_payload.size(), ZMQ_DONTWAIT);
    }
  }

  CAEN_DGTZ_SWStopAcquisition(handle);
  std::cout << "\n\033[1;31m[DAQManager] Stopped Acquisition B" << link_num_ << ".\033[0m\n";

  auto end_wall = std::chrono::system_clock::now();
  auto t = std::chrono::system_clock::to_time_t(end_wall);
  auto tm = *std::localtime(&t);
  
  auto run_duration = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - start_time).count();
  
  // 절대 선속 라이브타임 계산
  double live_time_sec = (last_ttt_val - first_ttt_val) * TTT_RESOLUTION_NS * 1e-9;
  double dead_time_pct = 0.0;
  if (run_duration > 0 && live_time_sec > 0.0) {
      dead_time_pct = (1.0 - (live_time_sec / run_duration)) * 100.0;
      if (dead_time_pct < 0.0) dead_time_pct = 0.0; 
  }

  // 연구원님의 기존 출력 포맷 보존
  std::cout << "\n\033[1;36m========== [ DAQ Run Summary B" << link_num_ << " ] ==========\033[0m\n"
            << " - End Time        : " << std::put_time(&tm, "%Y-%m-%d %H:%M:%S") << "\n"
            << " - Total Time      : " << run_duration << " seconds\n"
            << " - Live Time       : " << std::fixed << std::setprecision(2) << live_time_sec << " seconds\n"
            << " - Dead Time Frac. : " << std::fixed << std::setprecision(4) << dead_time_pct << " %\n"
            << " - Total Events    : " << event_count << " events\n"
            << " - Avg Rate        : " << (run_duration > 0 ? (event_count / run_duration) : 0) << " Hz\n"
            << " - Data Size Saved : " << std::fixed << std::setprecision(2) << (total_bytes_written / (1024.0 * 1024.0)) << " MB\n"
            << "\033[1;36m===================================================\033[0m\n\n";

  std::string final_stat = "{\"live_time\":" + std::to_string(live_time_sec) + 
                           ",\"elapsed_time\":" + std::to_string(run_duration) + 
                           ",\"dead_time_pct\":" + std::to_string(dead_time_pct) + "}";
  zmq_send(zmq_pub_, "STAT", 4, ZMQ_SNDMORE);
  zmq_send(zmq_pub_, final_stat.c_str(), final_stat.size(), 0);

  if (auto_stopped) {
      zmq_send(zmq_pub_, "CTRL", 4, ZMQ_SNDMORE);
      zmq_send(zmq_pub_, "RUN_COMPLETED", 13, 0);
      std::this_thread::sleep_for(std::chrono::milliseconds(200)); 
  }
}
