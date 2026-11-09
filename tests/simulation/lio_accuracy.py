"""Independent SE(3) scoring; initial gauge alignment, never trajectory fitting."""
import math
import numpy as np
from vehicle_autonomy.contracts.core.geometry import Quaternion,Vector3
from vehicle_autonomy.world.transform.tree import multiply_quaternions,rotate_vector


def quaternion(value):return Quaternion(*map(float,value))
def inverse(q):return Quaternion(-q.x,-q.y,-q.z,q.w)
def angle(q):return math.degrees(2*math.acos(min(1.,abs(q.w))))
def rotate(q,p):
    v=rotate_vector(q,Vector3(*map(float,p)));return np.array([v.x,v.y,v.z])


def motion_excitation(truth):
    """Actual independent 6-DoF excitation, never an estimator input."""
    q=np.array([row['quaternion_xyzw'] for row in truth]);x,y,z,w=q.T
    roll=np.arctan2(2*(w*x+y*z),1-2*(x*x+y*y))
    pitch=np.arcsin(np.clip(2*(w*y-z*x),-1.,1.))
    yaw=np.unwrap(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
    return dict(height_span_m=float(np.ptp([row['z_m'] for row in truth])),
        roll_range_deg=float(np.degrees(np.ptp(roll))),pitch_range_deg=float(np.degrees(np.ptp(pitch))),
        yaw_range_deg=float(np.degrees(np.ptp(yaw))))


def score(records,truth,model_to_body=(0.,0.,0.)):
    # Every pairing uses the estimator's original acquisition stamp. The
    # judge interpolates only its own Gazebo history, never sends a pose back.
    by_time={row['simulation_ns']:row for row in truth};times=np.array(sorted(by_time),dtype=np.int64)
    paired=[]
    for row in records:
        t=row['capture_ros_ns'];i=int(np.searchsorted(times,t))
        if not 0<i<len(times):continue
        before,after=by_time[int(times[i-1])],by_time[int(times[i])]
        if times[i]-times[i-1]>200_000_000:continue
        a=(t-int(times[i-1]))/float(times[i]-times[i-1])
        p=(1-a)*np.array([before[k] for k in ('x_m','y_m','z_m')])+a*np.array([after[k] for k in ('x_m','y_m','z_m')])
        q1=np.array(before['quaternion_xyzw']);q2=np.array(after['quaternion_xyzw'])
        if np.dot(q1,q2)<0:q2=-q2
        q=q1*(1-a)+q2*a;q=q/np.linalg.norm(q)
        p=p+rotate(quaternion(q),model_to_body)
        paired.append((t,np.array(row['position']),quaternion(row['quaternion']),p,quaternion(q)))
    if len(paired)<20:raise ValueError('insufficient independently time-paired poses')
    first=paired[0];alignment=multiply_quaternions(first[4],inverse(first[2]));translation=first[3]-rotate(alignment,first[1])
    positions=np.array([rotate(alignment,v[1])+translation for v in paired]);actual=np.array([v[3] for v in paired])
    attitudes=[angle(multiply_quaternions(multiply_quaternions(alignment,v[2]),inverse(v[4]))) for v in paired]
    rpe=[]
    for i,v in enumerate(paired):
        j=next((j for j in range(i+1,len(paired)) if paired[j][0]-v[0]>=1_000_000_000),None)
        if j is None:continue
        if paired[j][0]-v[0]>1_150_000_000:continue
        estimated_rotation=multiply_quaternions(alignment,v[2])
        estimated_relative=rotate(inverse(estimated_rotation),positions[j]-positions[i])
        truth_relative=rotate(inverse(v[4]),actual[j]-actual[i])
        rpe.append(float(np.linalg.norm(estimated_relative-truth_relative)))
    if not rpe:raise ValueError('no one-second relative pose pairs')
    return dict(pairs=len(paired),alignment='first valid pose only; no trajectory fit',
        truth_origin='Gazebo model pose plus audited fixed model-to-body offset',model_to_body=list(model_to_body),
        ate_rmse_m=float(np.sqrt(np.mean(np.sum((positions-actual)**2,axis=1)))),
        rpe_1s_translation_rmse_m=float(np.sqrt(np.mean(np.square(rpe)))),
        attitude_rmse_deg=float(np.sqrt(np.mean(np.square(attitudes)))),
        return_drift_m=float(np.linalg.norm((positions[-1]-positions[0])-(actual[-1]-actual[0]))),
        truth_distance_m=float(np.linalg.norm(np.diff(actual,axis=0),axis=1).sum()),
        alignment_quaternion=[alignment.x,alignment.y,alignment.z,alignment.w],alignment_translation=translation.tolist())


def compare_optimization(records,optimized,truth,model_to_body=(0.,0.,0.)):
    """Compare actual raw/optimized poses at the SAME original capture cuts."""
    by_time={r['capture_ros_ns']:r for r in records};times=np.array(sorted(by_time),dtype=np.int64)
    raw=[];corrected=[]
    for row in optimized:
        stamp=row['capture_ros_ns'];index=int(np.searchsorted(times,stamp))
        candidates=[int(times[j]) for j in (index-1,index) if 0<=j<len(times) and abs(int(times[j])-stamp)<=2]
        if not candidates:continue
        original=by_time[min(candidates,key=lambda t:abs(t-stamp))]
        raw.append(original);corrected.append(row)
    if len(raw)<20:raise ValueError('insufficient same-capture optimization comparison')
    changes=np.linalg.norm(np.array([r['position'] for r in raw])-np.array([r['position'] for r in corrected]),axis=1)
    return dict(matched_cuts=len(raw),first_capture_ros_ns=raw[0]['capture_ros_ns'],last_capture_ros_ns=raw[-1]['capture_ros_ns'],
        raw=score(raw,truth,model_to_body),optimized=score(corrected,truth,model_to_body),
        correction_rms_m=float(np.sqrt(np.mean(changes**2))),correction_max_m=float(changes.max()),
        scope='same original capture times and same LIO initial gauge; no fresh timestamps or full-trajectory fitting')


def geometry(points,metrics,extra_columns=()):
    q=quaternion(metrics['alignment_quaternion']);t=np.array(metrics['alignment_translation'])
    values=np.array([rotate(q,p[:3])+t for p in points]);residuals=[np.abs(values[:,2])];names=['ground']
    for name,center,size in [('wall',(12,0,3),(.3,24,6)),('building',(-18,-14,5),(8,8,10)),
        *[(f'block{i}',(-10+i*4,-10,h/2),(1.5,1.5,h)) for i,h in enumerate((1,3,7))]]:
        d=np.abs(values-np.array(center))-np.array(size)/2
        # Signed distance to an axis-aligned box surface, absolute inside.
        sdf=np.linalg.norm(np.maximum(d,0),axis=1)+np.minimum(np.max(d,axis=1),0)
        residuals.append(np.abs(sdf));names.append(name)
    for i,(x,y,h) in enumerate(((8,-6,2),(8,6,5),(-8,8,3))+tuple(extra_columns)):
        radial=np.linalg.norm(values[:,:2]-[x,y],axis=1)-.4;vertical=np.abs(values[:,2]-h/2)-h/2
        d=np.column_stack([radial,vertical]);sdf=np.linalg.norm(np.maximum(d,0),axis=1)+np.minimum(np.max(d,axis=1),0)
        residuals.append(np.abs(sdf));names.append('column'+str(i))
    distance=np.stack(residuals,axis=1);nearest=distance.argmin(axis=1);errors=distance.min(axis=1)
    groups={name:int(((nearest==i)&(errors<=.2)).sum()) for i,name in enumerate(names)}
    return dict(geometry_residual_p95_m=float(np.quantile(errors,.95)),landmark_groups=groups,
        matching_landmark_groups=sum(count>=30 for count in groups.values()),points=len(points),
        oracle='analytic surfaces of the checked MID-360 static Gazebo fixtures; judge only')
