#ifndef CONFIG_PARSER_H
#define CONFIG_PARSER_H

#include <algorithm>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>

class ConfigParser {
public:
  ConfigParser(const std::string &filename) {
    std::ifstream file(filename);
    if (!file.is_open()) throw std::runtime_error("Cannot open config file: " + filename);
    std::string line, section;
    while (std::getline(file, line)) {
      auto comment_pos = line.find('#');
      if (comment_pos != std::string::npos) line = line.substr(0, comment_pos);
      line.erase(line.find_last_not_of(" \t\r\n") + 1);
      if (line.empty()) continue;
      if (line.front() == '[' && line.back() == ']') {
        section = line.substr(1, line.size() - 2);
      } else {
        auto delim = line.find('=');
        if (delim != std::string::npos) {
          std::string key = line.substr(0, delim);
          std::string val = line.substr(delim + 1);
          key.erase(key.find_last_not_of(" \t\r\n") + 1);
          val.erase(0, val.find_first_not_of(" \t\r\n"));
          data_[section][key] = val;
        }
      }
    }
  }

  int GetInt(const std::string &section, const std::string &key, int default_val = 0) const {
    auto sec_it = data_.find(section);
    if (sec_it != data_.end()) {
      auto key_it = sec_it->second.find(key);
      if (key_it != sec_it->second.end()) {
        try {
          return std::stoi(key_it->second); // 정상 변환 시도
        } catch (const std::exception& e) {
          return default_val; // 문자열 섞임 등 변환 실패 시 기본값 반환
        }
      }
    }
    return default_val;
  }

private:
  std::map<std::string, std::map<std::string, std::string>> data_;
};

#endif // CONFIG_PARSER_H