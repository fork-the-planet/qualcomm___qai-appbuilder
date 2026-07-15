#!/usr/bin/env python
"""Worth-clip quantitative classifier -- tensor-agnostic, pure-FP.

QNN/HTP quantization engineering practice. All LLM/Q-K/attention specifics removed;
the classifier itself is independent of tensor semantics.

Given a tensor's FP min/max, a quantization scheme (bitwidth, symmetric), and a
clip target (abs_p99 of |x|), decide whether clipping the outlier tail is worth
it, on a 4-tier scale.

Theory:
    granularity_gain = step_no_clip / step_with_clip
                     = full_fp_range / clip_range
                     = full_fp_range / (2 * abs_p99)
    where:
        full_fp_range = 2 * max(|fp_min|, |fp_max|)   if symmetric
                      = fp_max - fp_min                if asymmetric
        clip_range    = 2 * abs_p99

Decision tiers (calibrated empirically):
    gain < 2.0    -> NOT_WORTH   (INT resolution already fine)
    gain < 5.0    -> MARGINAL    (may be lost to calibration noise)
    gain < 20.0   -> WORTH       (clear accuracy gain expected)
    gain >= 20.0  -> CRITICAL    (outlier-dominated; must clip)

IMPORTANT: pick the actual clip threshold using output cosine / downstream task
metric, NOT SQNR. SQNR is dominated by the large-magnitude outliers and will
rank no-clip as "best" while the task metric collapses.
"""
import sys
import argparse

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

TIER_NOT_WORTH = "NOT_WORTH"
TIER_MARGINAL = "MARGINAL"
TIER_WORTH = "WORTH"
TIER_CRITICAL = "CRITICAL"

DEFAULT_THRESHOLDS = {
    "not_worth_max": 2.0,
    "marginal_max": 5.0,
    "worth_max": 20.0,
}

DEFAULT_PERCENTILE = 99.0


def worth_clipping(fp_min, fp_max, bw, symmetric, target_clip_abs,
                   thresholds=None):
    """Classify whether (fp_range, quant_scheme) benefits from outlier clipping.

    Args:
        fp_min, fp_max: float, observed FP tensor min/max.
        bw: int, quantization bitwidth (e.g. 4, 8, 16).
        symmetric: bool, True for symmetric (signed-int range).
        target_clip_abs: float, REQUIRED. abs_p99 of the FP tensor.
        thresholds: dict or None.

    Returns:
        dict with keys: granularity_gain, decision, reason, step_no_clip,
        step_with_clip, full_range, clip_range.
    """
    th = thresholds or DEFAULT_THRESHOLDS

    if symmetric:
        full_range = 2.0 * max(abs(fp_min), abs(fp_max))
        levels = float(2 ** bw - 1) if bw <= 8 else float(2 ** bw)
    else:
        full_range = float(fp_max) - float(fp_min)
        levels = float(2 ** bw)

    step_no_clip = full_range / levels if levels > 0 else float("inf")

    clip_range = 2.0 * float(target_clip_abs)
    step_with_clip = clip_range / levels if levels > 0 else float("inf")
    gain = step_no_clip / step_with_clip if step_with_clip > 0 else 0.0

    if gain < th["not_worth_max"]:
        decision = TIER_NOT_WORTH
        reason = (f"granularity gain {gain:.2f}x is below noise floor; "
                  f"INT{bw} resolution already fine relative to FP range")
    elif gain < th["marginal_max"]:
        decision = TIER_MARGINAL
        reason = (f"granularity gain {gain:.2f}x; may be lost in "
                  f"calibration run-to-run noise; benchmark recommended")
    elif gain < th["worth_max"]:
        decision = TIER_WORTH
        reason = (f"granularity gain {gain:.2f}x; clear accuracy improvement "
                  f"expected from clipping outliers")
    else:
        decision = TIER_CRITICAL
        reason = (f"granularity gain {gain:.2f}x; outlier-dominated tensor, "
                  f"clipping is mandatory for any reasonable quantization")

    return {
        "granularity_gain": gain,
        "decision": decision,
        "reason": reason,
        "step_no_clip": step_no_clip,
        "step_with_clip": step_with_clip,
        "full_range": full_range,
        "clip_range": clip_range,
    }


def abs_percentile_from_array(arr, percentile=DEFAULT_PERCENTILE):
    """Compute abs_p{N} of a tensor -- a pure property of the FP distribution.

    Args:
        arr: numpy array (any shape).
        percentile: percentile of |x| to use as the clip target.

    Returns:
        (abs_p, fp_min, fp_max)
    """
    a = np.asarray(arr).ravel().astype(np.float64)
    absx = np.abs(a)
    abs_p = float(np.percentile(absx, percentile))
    return abs_p, float(a.min()), float(a.max())


def parse_args():
    p = argparse.ArgumentParser(
        description="Worth-clip classifier (tensor-agnostic, pure-FP)")
    p.add_argument("--npy", default="",
                   help="Path to a .npy tensor; abs_p99/min/max auto-computed")
    p.add_argument("--fp-min", type=float, default=None)
    p.add_argument("--fp-max", type=float, default=None)
    p.add_argument("--abs-p99", type=float, default=None,
                   help="abs_p99 of |x| (required if --npy not given)")
    p.add_argument("--bw", type=int, default=8)
    p.add_argument("--symmetric", action="store_true", default=False)
    p.add_argument("--percentile", type=float, default=DEFAULT_PERCENTILE)
    return p.parse_args()


def main():
    args = parse_args()

    if args.npy:
        arr = np.load(args.npy, mmap_mode="r")
        abs_p, fp_min, fp_max = abs_percentile_from_array(arr, args.percentile)
        print(f"Loaded {args.npy}: shape={np.asarray(arr).shape}")
    else:
        if args.fp_min is None or args.fp_max is None or args.abs_p99 is None:
            sys.stderr.write(
                "ERROR: without --npy you must pass --fp-min --fp-max --abs-p99\n")
            sys.exit(2)
        fp_min, fp_max, abs_p = args.fp_min, args.fp_max, args.abs_p99

    res = worth_clipping(fp_min, fp_max, bw=args.bw,
                         symmetric=args.symmetric, target_clip_abs=abs_p)

    print(f"fp_min={fp_min:.4f}  fp_max={fp_max:.4f}  "
          f"abs_p{args.percentile:g}={abs_p:.4f}")
    print(f"bw={args.bw}  symmetric={args.symmetric}")
    print(f"full_range={res['full_range']:.4f}  clip_range={res['clip_range']:.4f}")
    print(f"granularity_gain={res['granularity_gain']:.2f}x")
    print(f"DECISION: {res['decision']}")
    print(f"reason: {res['reason']}")
    print()
    print("NOTE: to pick the actual clip value, sweep candidates and rank by "
          "output cosine / downstream task metric -- NOT SQNR (SQNR lies: it is "
          "dominated by the outliers you want to clip).")


if __name__ == "__main__":
    main()
