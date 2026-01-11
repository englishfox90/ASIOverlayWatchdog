import numpy as np
from astropy.io import fits

path = r"C:\Users\Paul Fox-Reeks\AppData\Local\PFRSentinel\raw_debug\raw_20260104_231143.fits"
data = np.asarray(fits.getdata(path))

print("shape:", data.shape, "dtype:", data.dtype)
print("min/max:", float(np.min(data)), float(np.max(data)))

def pcts(x):
    x = x.astype(np.float32)
    return [float(np.percentile(x, q)) for q in (0,1,50,99,99.9,100)]

if data.ndim == 2:
    print("2D Bayer-like frame. percentiles:", pcts(data))
    # quick CFA “separation” check for BGGR (B,G / G,R)
    B  = data[0::2, 0::2]
    G1 = data[0::2, 1::2]
    G2 = data[1::2, 0::2]
    R  = data[1::2, 1::2]
    print("BGGR planes mean (B,G1,G2,R):",
          float(B.mean()), float(G1.mean()), float(G2.mean()), float(R.mean()))
elif data.ndim == 3:
    # handle (3,H,W) or (H,W,3)
    if data.shape[0] == 3:
        r,g,b = data[0], data[1], data[2]
        print("3xHxW detected")
    elif data.shape[2] == 3:
        r,g,b = data[...,0], data[...,1], data[...,2]
        print("HxWx3 detected")
    else:
        raise SystemExit("Unexpected 3D shape")

    print("R pct:", pcts(r))
    print("G pct:", pcts(g))
    print("B pct:", pcts(b))
    # chroma energy check
    rgb = np.stack([r,g,b], axis=-1).astype(np.float32)
    y = 0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]
    c = rgb - y[...,None]
    print("mean |chroma|:", float(np.mean(np.abs(c))))
    print("corr(R,G), corr(G,B):",
          float(np.corrcoef(r.flatten(), g.flatten())[0,1]),
          float(np.corrcoef(g.flatten(), b.flatten())[0,1]))
else:
    print("Unexpected ndim:", data.ndim)
