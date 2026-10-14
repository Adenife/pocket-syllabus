"""Synchronize category definitions, including empty collections, conservatively."""
import hashlib
import json


def identity(item):
    return item['kind'],item['name'].casefold()


def signature(item):
    if item is None: return None
    return hashlib.sha256(json.dumps([*identity(item),item.get('description','')]).encode()).hexdigest()


def synchronize(local,remote,state,before_left,before_right):
    left={item['id']:item for item in local.catalog()}
    right={item['id']:item for item in remote.catalog()}
    original_left={item['id'] for item in before_left}
    original_right={item['id'] for item in before_right}
    pairs=state.setdefault('catalog_pairs',[])
    conflicts=[];used_left=set();used_right=set();changed=0

    def conflict(item):
        conflicts.append('category:'+item['kind']+':'+item['name'])

    def update(source,target,peer,all_targets,original_targets):
        # Portable document metadata may have created the renamed category already.
        other=next((item for item in all_targets.values() if item['id']!=target['id'] and identity(item)==identity(source)),None)
        if other:
            if target.get('membership_count',0):
                conflict(source);return None
            if other['id'] in original_targets and other.get('description','')!=source.get('description',''):
                conflict(source);return None
            peer.delete_category(target)
            all_targets.pop(target['id'],None)
            target=other
        result=peer.update_category(target,source)
        all_targets[result['id']]=result
        return result

    for pair in list(pairs):
        a=left.get(pair.get('left_id'));b=right.get(pair.get('right_id'))
        if a: used_left.add(a['id'])
        if b: used_right.add(b['id'])
        sa,sb=signature(a),signature(b)
        lc=sa!=pair.get('left_sig');rc=sb!=pair.get('right_sig')
        if lc and rc and sa!=sb:
            conflict(a or b);continue
        if lc and not rc:
            if a is None:
                if b and b.get('membership_count',0): conflict(b);continue
                if b: remote.delete_category(b);right.pop(b['id'],None)
                pair.update(left_id=None,right_id=None,left_sig=None,right_sig=None);changed+=1
            elif b:
                result=update(a,b,remote,right,original_right)
                if result is None: continue
                pair.update(right_id=result['id'],left_sig=sa,right_sig=signature(result));used_right.add(result['id']);changed+=1
            else:
                conflict(a)
        elif rc and not lc:
            if b is None:
                if a and a.get('membership_count',0): conflict(a);continue
                if a: local.delete_category(a);left.pop(a['id'],None)
                pair.update(left_id=None,right_id=None,left_sig=None,right_sig=None);changed+=1
            elif a:
                result=update(b,a,local,left,original_left)
                if result is None: continue
                pair.update(left_id=result['id'],right_sig=sb,left_sig=signature(result));used_left.add(result['id']);changed+=1
            else:
                conflict(b)
        else:
            pair.update(left_sig=sa,right_sig=sb)

    for a in list(left.values()):
        if a['id'] in used_left: continue
        b=next((item for item in right.values() if identity(item)==identity(a)),None)
        if b and b['id'] in used_right:
            conflict(a);continue
        if b and signature(a)!=signature(b):
            if b['id'] not in original_right:
                b=remote.update_category(b,a);right[b['id']]=b;changed+=1
            elif a['id'] not in original_left:
                a=local.update_category(a,b);left[a['id']]=a;changed+=1
            else:
                conflict(a)
                pairs.append({'left_id':a['id'],'right_id':b['id'],'left_sig':None,'right_sig':None})
                used_left.add(a['id']);used_right.add(b['id']);continue
        if b is None:
            b=remote.create_category(a);right[b['id']]=b;changed+=1
        pairs.append({'left_id':a['id'],'right_id':b['id'],'left_sig':signature(a),'right_sig':signature(b)})
        used_left.add(a['id']);used_right.add(b['id'])
    for b in list(right.values()):
        if b['id'] in used_right: continue
        a=local.create_category(b);left[a['id']]=a;changed+=1
        pairs.append({'left_id':a['id'],'right_id':b['id'],'left_sig':signature(a),'right_sig':signature(b)})
        used_left.add(a['id']);used_right.add(b['id'])
    state['catalog_pairs']=[pair for pair in pairs if pair.get('left_id') or pair.get('right_id')]
    return changed,list(dict.fromkeys(conflicts))
