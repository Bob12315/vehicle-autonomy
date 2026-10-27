// Read-only public rclcpp MessageInfo adapter. No vehicle/protocol dependency.
#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist_stamped.hpp>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <time.h>
#include <array>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <stdexcept>

#pragma pack(push, 1)
struct Frame {
  char magic[8]; uint8_t channel; uint8_t gid_size; uint16_t reserved;
  uint64_t stamp; uint64_t received;
  double values[6]; uint8_t gid[24]; char frame[64];
};
#pragma pack(pop)
static_assert(sizeof(Frame)==164);

int main(int argc,char **argv) {
  rclcpp::init(argc,argv);
  auto args=rclcpp::remove_ros_arguments(argc,argv); std::string socket_path,ns;
  for (size_t i=1;i+1<args.size();i+=2) {
    if(args[i]=="--socket") socket_path=args[i+1];
    else if(args[i]=="--namespace") ns=args[i+1];
    else throw std::runtime_error("unknown read-only receiver option");
  }
  if(socket_path.empty() || socket_path.size()>=sizeof(sockaddr_un::sun_path) || ns.empty() || ns[0]!='/') throw std::runtime_error("explicit owned receiver endpoint required");
  int fd=socket(AF_UNIX,SOCK_DGRAM|SOCK_NONBLOCK|SOCK_CLOEXEC,0);
  if(fd<0) throw std::runtime_error("receiver socket unavailable");
  sockaddr_un destination{};destination.sun_family=AF_UNIX;
  std::memcpy(destination.sun_path,socket_path.c_str(),socket_path.size()+1);
  socklen_t destination_size=sizeof(destination);
  if(socket_path[0]=='@') {destination.sun_path[0]='\0';destination_size=offsetof(sockaddr_un,sun_path)+socket_path.size();}
  auto options=rclcpp::NodeOptions().start_parameter_services(false);
  auto node=std::make_shared<rclcpp::Node>("vaf_native_source_receiver",options);
  std::array<rclcpp::Subscription<geometry_msgs::msg::TwistStamped>::SharedPtr,2> subscriptions;
  const std::array<std::string,2> topics={ns+"/cmd_vel_nav",ns+"/cmd_vel_final"};
  for(size_t channel=0;channel<topics.size();++channel) {
    subscriptions[channel]=node->create_subscription<geometry_msgs::msg::TwistStamped>(topics[channel],rclcpp::QoS(10),
      [&,channel](geometry_msgs::msg::TwistStamped::ConstSharedPtr message,const rclcpp::MessageInfo &info) {
        if(message->header.frame_id.size()>=64 || message->header.stamp.sec<0) return;
        Frame frame{};std::memcpy(frame.magic,"VAFNV01",7);frame.channel=channel;frame.gid_size=RMW_GID_STORAGE_SIZE;
        static_assert(RMW_GID_STORAGE_SIZE<=24);
        frame.stamp=uint64_t(message->header.stamp.sec)*1000000000ULL+message->header.stamp.nanosec;
        timespec now{};clock_gettime(CLOCK_MONOTONIC,&now);frame.received=uint64_t(now.tv_sec)*1000000000ULL+now.tv_nsec;
        frame.values[0]=message->twist.linear.x;frame.values[1]=message->twist.linear.y;frame.values[2]=message->twist.linear.z;
        frame.values[3]=message->twist.angular.x;frame.values[4]=message->twist.angular.y;frame.values[5]=message->twist.angular.z;
        const auto &metadata=info.get_rmw_message_info();std::memcpy(frame.gid,metadata.publisher_gid.data,RMW_GID_STORAGE_SIZE);
        std::memcpy(frame.frame,message->header.frame_id.data(),message->header.frame_id.size());
        // A full IPC socket drops this sample; it never waits or renews age.
        sendto(fd,&frame,sizeof(frame),MSG_DONTWAIT,reinterpret_cast<sockaddr*>(&destination),destination_size);
      });
  }
  rclcpp::spin(node);node.reset();close(fd);rclcpp::shutdown();return 0;
}
