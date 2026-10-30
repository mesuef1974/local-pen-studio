"""Experimental raster correction. Source edge evidence is NOT semantic ground truth."""
import cv2
import numpy as np

VERSION = 'conservative-line-correction/0.1'


def source_evidence(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    masks = [cv2.Canny(cv2.GaussianBlur(gray, (0,0), sigma), 40, 100) > 0
             for sigma in (.8, 1.6)]
    stable = masks[0] & (cv2.dilate(masks[1].astype('uint8'), np.ones((3,3),'uint8')) > 0)
    return stable


def components(mask):
    return cv2.connectedComponentsWithStats(mask.astype('uint8'), 8)


def holes(mask):
    _, hierarchy = cv2.findContours(mask.astype('uint8'), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    return 0 if hierarchy is None else int(np.sum(hierarchy[0,:,3] >= 0))


def junctions(mask):
    skeleton = cv2.ximgproc.thinning(mask.astype('uint8')*255) > 0
    neighbours = cv2.filter2D(skeleton.astype('uint8'), -1, np.ones((3,3),'uint8'))
    return skeleton & (neighbours >= 4)


def correct(mask, evidence, regions, protected=None, max_edits=6):
    """All thresholds are prototype constants in input pixels, not calibrated confidence."""
    mask = np.asarray(mask, bool)
    evidence = np.asarray(evidence, bool)
    regions = np.asarray(regions, np.uint8)
    protected = np.zeros_like(mask) if protected is None else np.asarray(protected, bool)
    if mask.ndim != 2 or any(x.shape != mask.shape for x in (evidence,regions,protected)):
        raise ValueError('Masks must have identical 2D shapes.')
    if not evidence.any() or not regions.any():
        return mask.copy(), {'version': VERSION, 'operations': [], 'changedPixels': 0,
                             'state': 'abstained', 'reason': 'No source evidence or configured region.'}
    result = mask.copy()
    distance = cv2.distanceTransform((~evidence).astype('uint8'), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    operations = []
    # Tiny isolated specks only. Protect all supplied feature anchors and neighbourhoods.
    count, labels, stats, _ = components(result)
    for label in range(1, count):
        if len(operations) >= max_edits:
            break
        if stats[label, cv2.CC_STAT_AREA] > 2:
            continue
        bx,by,bw,bh = stats[label,:4]
        if not regions[by:by+bh,bx:bx+bw].any():
            continue
        part = labels == label
        if not np.all(regions[part] > 0) or protected[part].any() or np.min(distance[part]) <= 3:
            continue
        nearby = cv2.dilate(part.astype('uint8'), np.ones((9,9),'uint8')) > 0
        if (result & ~part & nearby).any():
            continue
        result[part] = False
        y,x = np.where(part)
        operations.append({'kind': 'remove_speck', 'pixels': int(part.sum()),
            'box': [int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)],
            'reason': 'At most two isolated pixels; no nearby persistent edge; outside anchor protection.'})
    # Translate only a small isolated component with unique, substantially stronger local support.
    count, labels, stats, _ = components(result)
    for label in range(1, count):
        if len(operations) >= max_edits:
            break
        area = stats[label, cv2.CC_STAT_AREA]
        if not 12 <= area <= 160 or max(stats[label,2:4]) > 40:
            continue
        bx,by,bw,bh = stats[label,:4]
        if not regions[by:by+bh,bx:bx+bw].any():
            continue
        part = labels == label
        ids = np.unique(regions[part])
        if len(ids) != 1 or ids[0] == 0 or protected[part].any():
            continue
        ys,xs = np.where(part)
        baseline = float(np.mean(np.exp(-(distance[part]/.65)**2)))
        if baseline >= .6:
            continue
        candidates = []
        for dy in range(-2,3):
            for dx in range(-2,3):
                if dx == dy == 0 or dx*dx+dy*dy > 4:
                    continue
                ny,nx = ys+dy,xs+dx
                if min(ny.min(),nx.min()) < 0 or ny.max() >= mask.shape[0] or nx.max() >= mask.shape[1]:
                    continue
                if not np.all(regions[ny,nx] == ids[0]) or protected[ny,nx].any():
                    continue
                target = np.zeros_like(result); target[ny,nx] = True
                if ((cv2.dilate(target.astype('uint8'),np.ones((3,3),'uint8')) > 0) & result & ~part).any():
                    continue
                candidates.append((float(np.mean(np.exp(-(distance[ny,nx]/.65)**2))),dx,dy,target))
        candidates.sort(key=lambda c:c[0], reverse=True)
        if len(candidates) < 2 or candidates[0][0] < .95 or candidates[0][0]-baseline < .4 or candidates[0][0]-candidates[1][0] < .15:
            continue
        score,dx,dy,target = candidates[0]
        proposed = (result & ~part) | target
        if holes(proposed) != holes(result) or components(proposed)[0] != components(result)[0]:
            continue
        result = proposed
        operations.append({'kind': 'translate_component', 'dx': dx, 'dy': dy,
            'pixels': int(area), 'supportBefore': baseline, 'supportAfter': score,
            'reason': 'Unique bounded offset; no merge, protected anchor overlap, or new closed hole.'})
    # Bridge only different components with facing endpoints, a short supported straight gap.
    skeleton = cv2.ximgproc.thinning(result.astype('uint8')*255) > 0
    neighbours = cv2.filter2D(skeleton.astype('uint8'), -1, np.ones((3,3),'uint8'))
    endpoints = np.argwhere(skeleton & (neighbours == 2) & (regions > 0) & ~protected)
    used_endpoints = set()
    if len(endpoints) <= 600:
        for i,(y,x) in enumerate(endpoints):
            if len(operations) >= max_edits:
                break
            for yy,xx in endpoints[i+1:]:
                if (int(y),int(x)) in used_endpoints or (int(yy),int(xx)) in used_endpoints:
                    continue
                length = float(np.hypot(xx-x,yy-y))
                if not 2 <= length <= 4 or regions[y,x] != regions[yy,xx]:
                    continue
                _, labels, _, _ = components(result)
                if labels[y,x] == labels[yy,xx]:
                    continue
                directions = []
                for ey,ex in [(y,x),(yy,xx)]:
                    local = np.argwhere(skeleton[max(0,ey-1):ey+2,max(0,ex-1):ex+2])
                    local += [max(0,ey-1),max(0,ex-1)]
                    local = local[(local[:,0] != ey) | (local[:,1] != ex)]
                    directions.append(np.array([ey,ex])-local[0] if len(local)==1 else None)
                vector = np.array([yy-y,xx-x])
                if any(v is None for v in directions):
                    continue
                if np.dot(directions[0],vector)/np.linalg.norm(directions[0])/length < .9 or np.dot(directions[1],-vector)/np.linalg.norm(directions[1])/length < .9:
                    continue
                bridge = np.zeros_like(result, dtype='uint8')
                cv2.line(bridge,(int(x),int(y)),(int(xx),int(yy)),1,1)
                added = (bridge > 0) & ~result
                if not added.any() or protected[added].any() or np.max(distance[added]) > 1 or np.any(regions[added] != regions[y,x]):
                    continue
                # Evidence must cross the gap, not just lie at the two existing endpoints.
                normal = np.array([-(xx-x), yy-y])/length
                supported = True
                for ay,ax in np.argwhere(added):
                    probes = np.rint(np.array([ay,ax])+np.array([-1,0,1])[:,None]*normal).astype(int)
                    probes = probes[(probes[:,0]>=0)&(probes[:,0]<mask.shape[0])&(probes[:,1]>=0)&(probes[:,1]<mask.shape[1])]
                    if not evidence[probes[:,0],probes[:,1]].any():
                        supported = False
                        break
                if not supported:
                    continue
                proposed = result | added
                if holes(proposed) != holes(result) or components(proposed)[0] != components(result)[0]-1:
                    continue
                old_junction_area = cv2.dilate(junctions(result).astype('uint8'),np.ones((3,3),'uint8')) > 0
                if (junctions(proposed) & ~old_junction_area).any():
                    continue
                result = proposed
                used_endpoints.update([(int(y),int(x)),(int(yy),int(xx))])
                operations.append({'kind':'bridge_gap','pixels':int(added.sum()),
                    'from':[int(x),int(y)],'to':[int(xx),int(yy)],
                    'reason':'Facing endpoints; 2–4 px gap; different components; persistent edge support; no new hole.'})
                break
    # Roll back the whole image if the tiny editing budget was exceeded.
    changed = int(np.sum(mask != result))
    budget = max(4, int(mask.sum()*.005))
    if changed > budget:
        return mask.copy(), {'version': VERSION,'operations': [],'state':'rolled_back',
                             'changedPixels':0,'reason':'Exceeded 0.5% ink-change budget (minimum four pixels).'}
    return result, {'version': VERSION, 'operations': operations,'changedPixels':changed,
                    'state':'edited' if changed else 'abstained','changeBudget':budget,
                    'automaticApproval':False, 'semanticGroundTruth':False}
