"""Bounded identity candidates, never observations or target-lock authority."""


class TargetAssociator:
    def __init__(self):self.tracks={};self.number=0

    def update(self,detections,now_ns):
        """Return IDs only for this new qualified frame; absence returns nothing.

        A brief sync outage may retain candidates for five seconds. This covers
        the Action's one-second observation TTL plus three-second reacquisition
        window; it never extends either deadline. Matching
        always needs a new pixel detection and projection, with one-to-one,
        same-class/backend, unique proximity. No old observation is republished.
        """
        self.tracks={k:v for k,v in self.tracks.items() if 0<=now_ns-v[3]<5_000_000_000}
        candidates=[]
        for point,label,backend in detections:
            candidates.append([key for key,value in self.tracks.items()
                if value[2]==label and value[4]==backend
                and (point.x-value[0])**2+(point.y-value[1])**2<.5**2])
        counts={key:sum(key in row for row in candidates) for row in candidates for key in row}
        result=[]
        for index,((point,label,backend),choices) in enumerate(zip(detections,candidates)):
            unique=not any(i!=index and label==other_label and backend==other_backend
                and (point.x-other.x)**2+(point.y-other.y)**2<.5**2
                for i,(other,other_label,other_backend) in enumerate(detections))
            if unique and len(choices)==1 and counts[choices[0]]==1:key=choices[0]
            else:self.number+=1;key='target-'+str(self.number)
            # Ambiguous fragments may be reported as new detections, but must
            # not poison future identity matching or renew an existing lock.
            if unique:self.tracks[key]=(point.x,point.y,label,now_ns,backend)
            result.append(key)
        return result
