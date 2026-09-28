"""Normalize the two coordinate encodings emitted by parser/recovery adapters."""

def rectangle(coord):
    if 'bbox' in coord:
        box=coord['bbox']
        if not isinstance(box,(list,tuple)) or len(box)!=4:
            raise ValueError('Invalid evidence bbox')
        return tuple(box)
    return coord['x'],coord['y'],coord['x']+coord['width'],coord['y']+coord['height']


def overlaps(a,b):
    if a['page']!=b['page']:
        return False
    ax,ay,ar,ab=rectangle(a);bx,by,br,bb=rectangle(b)
    return min(ar,br)>max(ax,bx) and min(ab,bb)>max(ay,by)
