// Local opt-in SLAM Toolbox 2.8.5 occupancy allocation overlay.
// Upstream SMapper attribution: (c) 2018 Simbe Robotics / Steve Macenski,
// (c) 2019 Samsung Research America. Upstream package declares LGPL.
// Karto SDK inline code: (c) 2010 SRI International, LGPL-3.0-or-later.
// See the preserved upstream licenses and NATIVE_NOTICES.md.
// Only dimensions change; scan matching and original ray tracing stay.
#include "slam_toolbox/slam_mapper.hpp"
#include <cstdio>
#include <mutex>
karto::OccupancyGrid * mapper_utils::SMapper::getOccupancyGrid(const double & resolution) {
  static std::once_flag report;
  std::call_once(report, [] { std::fprintf(stderr,"VAF_BOUNDARY_OVERLAY_ACTIVE\n"); });
  return karto::OccupancyGrid::CreateFromScans(mapper_->GetAllProcessedScans(), resolution,
    (kt_int32u)mapper_->getParamMinPassThrough(), (kt_double)mapper_->getParamOccupancyThreshold());
}
