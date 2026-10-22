#include "karto_sdk/Karto.h"
#include <iostream>
int main() {
 auto *laser=karto::LaserRangeFinder::CreateLaserRangeFinder(karto::LaserRangeFinder_Custom,karto::Name("test"));
 laser->SetMinimumAngle(-karto::KT_PI);laser->SetMaximumAngle(karto::KT_PI);laser->SetAngularResolution(karto::KT_PI/2);
 laser->SetMinimumRange(.1);laser->SetMaximumRange(12);laser->SetRangeThreshold(12);
 karto::SensorManager::GetInstance()->RegisterSensor(laser);
 karto::RangeReadingsVector ranges(laser->GetNumberOfRangeReadings(),3.9);
 karto::LocalizedRangeScan scan(karto::Name("test"),ranges);scan.SetCorrectedPose(karto::Pose2(0,0,0));
 karto::LocalizedRangeScanVector scans;scans.push_back(&scan);
 auto *g=karto::OccupancyGrid::CreateFromScans(scans,.05,1,.1);
 int dropped=0;for(auto p:scan.GetPointReadings()) if(!g->IsValidGridIndex(g->WorldToGrid(p))) ++dropped;
 std::cout<<"{\"width\":"<<g->GetWidth()<<",\"height\":"<<g->GetHeight()<<",\"dropped_endpoints\":"<<dropped<<"}"<<std::endl;
 delete g;return dropped?1:0;
}
