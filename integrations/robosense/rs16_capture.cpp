// VAF adapter using the separately fetched official BSD-3-Clause rs_driver.
// No vehicle commands, network interface configuration or sensor configuration writes.
#include <cstdint> // official header requires caller to include fixed-width integers
#include <memory>
#include <rs_driver/api/lidar_driver.hpp>
#include <rs_driver/msg/point_cloud_msg.hpp>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <thread>
#include <unistd.h>
using namespace robosense::lidar;
using Cloud = PointCloudT<PointXYZI>;
std::atomic<bool> running{true};
std::mutex cloud_mutex;
std::shared_ptr<Cloud> latest;
void finish(int) { running = false; }
long long monotonic_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
int main(int argc, char** argv) {
  if (argc != 7 && argc != 8) {
    std::cerr << "Usage: rs16_capture HOST_IP MSOP_PORT DIFOP_PORT SECONDS OUTPUT_JSON EPOCH [PCAP]\n";
    return 2;
  }
  const std::string output(argv[5]), epoch(argv[6]);
  if (output.empty() || output[0] != '/' || epoch.empty() ||
      epoch.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != std::string::npos) return 2;
  const int msop=std::stoi(argv[2]), difop=std::stoi(argv[3]), seconds=std::stoi(argv[4]);
  if (msop<1024 || msop>65535 || difop<1024 || difop>65535 || msop==difop || seconds<1 || seconds>86400) return 2;
  const bool pcap=argc==8;
#ifdef DISABLE_PCAP_PARSE
  if (pcap) { std::cerr << "PCAP not compiled; install libpcap in an isolated toolchain\n"; return 2; }
#endif
  std::string boot; std::ifstream("/proc/sys/kernel/random/boot_id") >> boot;
  RSDriverParam param;
  param.lidar_type=LidarType::RS16;
  param.input_type=pcap?InputType::PCAP_FILE:InputType::ONLINE_LIDAR;
  param.input_param.host_address=argv[1];
  param.input_param.msop_port=msop; param.input_param.difop_port=difop;
  if (pcap) { param.input_param.pcap_path=argv[7]; param.input_param.pcap_repeat=false; }
  param.decoder_param.use_lidar_clock=false;
  param.decoder_param.wait_for_difop=true;
  LidarDriver<Cloud> driver;
  driver.regPointCloudCallback([](){return std::make_shared<Cloud>();}, [](std::shared_ptr<Cloud> cloud){
    std::lock_guard<std::mutex> lock(cloud_mutex); latest=cloud;
  });
  driver.regExceptionCallback([](const Error& error){std::cerr << error.toString() << '\n';});
  std::signal(SIGINT,finish); std::signal(SIGTERM,finish);
  if (!driver.init(param) || !driver.start()) return 1;
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(seconds);
  unsigned accepted=0;
  while (running && std::chrono::steady_clock::now()<deadline) {
    std::shared_ptr<Cloud> cloud;
    { std::lock_guard<std::mutex> lock(cloud_mutex); cloud.swap(latest); }
    if (!cloud) { std::this_thread::sleep_for(std::chrono::milliseconds(10)); continue; }
    if (cloud->points.size()>200000) { std::cerr << "cloud point budget exceeded\n"; continue; }
    const long long received=monotonic_ns();
    const double realtime=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
    const double age=realtime-cloud->timestamp;
    if (!std::isfinite(age) || age<0 || age>.5) { std::cerr << "invalid SDK capture timestamp\n"; continue; }
    const auto temporary=output+".tmp."+std::to_string(getpid());
    std::ofstream stream(temporary, std::ios::trunc);
    stream << std::setprecision(12) << "{\"schema\":1,\"source\":\"robosense.rs_driver\",\"epoch\":\"" << epoch
      << "\",\"clock_domain\":\"" << boot << "\",\"frame\":\"lidar\",\"sequence\":" << cloud->seq
      << ",\"capture_ns\":" << received-static_cast<long long>(age*1e9) << ",\"receive_ns\":" << received
      << ",\"source_timestamp_s\":" << cloud->timestamp << ",\"provenance\":\"" << (pcap?"pcap_replay":"live_sdk_system_timestamp")
      << "\",\"points\":[";
    bool first=true;
    for (const auto& point:cloud->points) {
      if (!std::isfinite(point.x)||!std::isfinite(point.y)||!std::isfinite(point.z)) continue;
      if (!first) stream << ',';
      first=false; stream << '[' << point.x << ',' << point.y << ',' << point.z << ']';
    }
    stream << "]}\n"; stream.close();
    if (!stream || std::rename(temporary.c_str(),output.c_str())!=0) { driver.stop(); return 1; }
    accepted++;
  }
  driver.stop();
  std::cerr << "decoded_clouds=" << accepted << '\n';
  return accepted?0:3;
}
