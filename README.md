
# HEP 3-Tier DAQ Control Center for CAEN DT5730S

![Platform](https://img.shields.io/badge/Platform-Linux-blue)
![C++](https://img.shields.io/badge/C++-17-00599C?logo=c%2B%2B)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python)
![ROOT](https://img.shields.io/badge/ROOT-6-black)
![License](https://img.shields.io/badge/License-MIT-green)

본 프로젝트는 입자 및 핵물리 실험(고분해능 무기 섬광체 등)을 위한 **CAEN DT5730S 디지타이저 기반의 하이브리드 데이터 수집(DAQ) 시스템**입니다. 

기존 일체형(Monolithic) DAQ 소프트웨어가 가지는 UI 렌더링 병목 현상과 메모리 누수 문제를 원천 차단하기 위해, **데이터 생산(C++)과 소비(Python)를 물리적으로 완벽히 분리(Decoupling)한 3-Tier 아키텍처**로 설계되었습니다. 

최신 업데이트를 통해 다중 채널 비트마스크 파싱, SQLite 기반 측정 이력 영구 보존, 동적 HTML 색상 로그, 그리고 대화형 ROOT 분석 프레임워크가 완벽히 결합된 상용(Commercial) 프로덕션 레벨의 완성도를 제공합니다.

## 🏛️ System Architecture (제1원리 설계)

시스템은 역할에 따라 세 가지 계층으로 완전히 분리되어 작동합니다.

1. **Tier 1: High-Speed Frontend (C++)**
   * **역할:** 하드웨어 제어 및 Raw 데이터 초고속 기록.
   * **특징:** 무거운 소프트웨어 DSP 연산을 배제하고 **24 Bytes 초경량 헤더**와 순수 파형(Waveform)만 디스크(`.dat`)에 기록하여 USB 대역폭과 디스크 I/O를 극대화합니다. 실시간 전송 속도(MB/s)를 자체 연산합니다.
   * **통신:** 수집된 데이터는 비동기 논블로킹(Non-blocking) 방식의 **ZeroMQ (PUB/SUB)** 소켓을 통해 브로드캐스팅됩니다. GUI의 상태와 무관하게 수집 프로세스는 절대 지연되지 않습니다.

2. **Tier 2: Offline Production (C++ & ROOT)**
   * **역할:** 이진 데이터(`.dat`)를 물리 분석용 ROOT 형식(`.root`)으로 고속 변환.
   * **특징:** 파일 포인터 점프(fseek) 기법을 활용해 파형 저장이 불필요할 경우 변환 속도를 10배 이상 끌어올렸으며, 특정 이벤트의 아날로그 파형을 즉각적으로 확인할 수 있는 **Interactive Debugging Mode (`-d`)**를 네이티브 지원합니다.

3. **Tier 3: Control Center GUI (Python PyQt5)**
   * **역할:** 실험 환경의 직관적인 제어 및 엣지 컴퓨팅(Edge Computing) 기반의 실시간 모니터링.
   * **특징:** C++ 프론트엔드를 QThread 워커로 구동하여 표준 출력을 낚아채고(Stream Routing), 데이터를 분기하여 2단 대시보드 메트릭과 시인성 높은 **HTML 기반 동적 컬러 로그**를 렌더링합니다.

## ✨ Key Features

* **Multi-Channel Edge Computing Monitor:** Python 워커 스레드가 수신된 ZMQ 패킷의 `ChannelMask`를 Bitwise 연산으로 역산출하여, 사용자가 선택한 특정 채널(Target CH)의 바이트 오프셋(Offset)만 정확히 도려내어 실시간 스펙트럼 적분을 수행합니다. (Clear 기능 지원)
* **Continuous / Batch Mode:** 단일 구동뿐만 아니라, 지정된 이벤트 수(-n)나 시간(-t) 단위로 파일 번호를 자동 증가(`_part01`, `_part02`)시키며 분할 저장하는 무한 백그라운드 배치 모드를 지원합니다.
* **SQLite Run Database:** DAQ가 구동될 때마다 Run ID, 측정 일시, 출력 파일명, 사용자가 기입한 고전압(HV) 값, 그리고 **당시 장비에 인가된 `.conf` 설정 파일의 전체 스냅샷**을 `run_history.db`에 영구 기록 및 추적합니다.
* **Smart UI/UX:** `pyqtgraph` 기반의 최적화된 연회색 라이트 테마 플로팅, 원클릭 디스크 잔여 용량 감시, 파일 시스템 브라우저 연동, 그리고 CPU 점유율 최적화를 위한 모니터링 토글 스위치를 내장하고 있습니다.

## ⚙️ Prerequisites

* **OS:** Linux (Rocky Linux 8/9, CentOS 7, Ubuntu 20.04+ recommended)
* **CAEN Libraries & Drivers (필수 설치):**
  * `CAENUSB` (USB 커널 드라이버)
  * `CAENVME` (CAENVMELib)
  * `CAENComm`
  * `CAENDigitizer` (v1.0 버전)
  > ⚠️ **[주의] 커널(Kernel) 업데이트 관련:** Linux OS의 커널 버전이 업데이트될 경우, 기존에 빌드된 `CAENUSB` 커널 모듈(드라이버)의 종속성이 끊어져 장치를 인식하지 못합니다. **OS 커널 업데이트 직후에는 반드시 `CAENUSB` 소스 디렉토리로 이동하여 설치 스크립트(예: `sudo sh install` 을 이용한 DKMS 빌드)를 재실행**해야 합니다.
  > 신형 장비 경우 libusb-1.0 라이브러리를 이용함에 따라 커널 모듈 종속성에 대하여 유연하게 대처할 수 있습니다. 
* **Data Libraries:** 
  * ROOT 6 (built with C++17 지원 플래그)
  * ZeroMQ (`libzmq3-dev`)
* **Python Libraries:** 
  * `PyQt5`, `pyqtgraph`, `numpy`, `pyzmq`

## 🚀 Build & Installation

CMake를 활용하여 C++ 백엔드를 빌드함과 동시에, GUI 구동을 위한 Python 모듈들이 `bin/` 디렉토리로 자동 배포(Deployment)됩니다.

```bash
git clone https://github.com/opercjy/CPNR_dt5730s.git
cd CPNR_dt5730s
mkdir build && cd build
cmake ..
make -j4
```

## 🖥️ Usage

빌드가 완료되면 생성된 래퍼 스크립트를 통해 GUI를 즉시 실행할 수 있습니다. (작업 디렉토리가 자동으로 `bin/`으로 고정됩니다.)

```bash
./bin/daq_gui
```

### GUI 탭(Tab)별 기능 명세서
* **🚀 DAQ Control:** 파일 브라우저 연동, 인가 전압(HV) 기입, 런 조건(Events/Time) 및 분할 배치 모드 설정. 2단 실시간 대시보드(Storage, Hz, MB/s, ZMQ Drops 등) 및 컬러 파싱 터미널 창 제공.
* **⚙️ Hardware Config:** 장비 조준경(DCOffset, Threshold, RecordLength 등)을 GUI 상의 표(TableWidget)에서 즉시 편집하고 `.conf`에 반영(Single Source of Truth).
* **📈 Live Monitor:** ZMQ 소켓 실시간 파형(Waveform) 모니터링 및 에너지 전하량(Q-Long) 동적 적분 스펙트럼. Target Channel 선택 및 히스토그램 Clear 지원.
* **🔬 Offline Production:** `.dat` -> `.root` 변환 전담. 변환 시간(ETA) 출력 기능 및 특정 Event ID 하드코어 팝업 디버깅(-d).
* **🗄️ Run DB History:** SQLite 데이터베이스에 기록된 과거 측정 이력 리스트업.

## 👨‍🔬 Author & Acknowledgment

* **Ji-young Choi (최지영)** 
  * Nuclear and Particle Physicist
  * Department of Physics, Center for Precision Neutrino Research (CPNR), Chonnam National University
* 본 프로젝트는 오픈소스 제1원칙에 따라 공공의 이익을 위해 설계 및 투명하게 공개되었습니다.
